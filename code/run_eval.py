"""Run the grounding experiment.

Each question is asked under three conditions:
  schema   - table DDL only
  tables   - DDL + table metadata (metadata/tables.yaml)
  lineage  - DDL + table metadata + lineage (metadata/lineage.yaml)

Providers:
  oracle     - answers with the gold SQL (checks the pipeline, should score 100%)
  naive      - answers with the naive SQL a schema-only analyst would write (lower bound)
  anthropic  - Claude through the Anthropic API (needs ANTHROPIC_API_KEY in the environment)
  openai     - any OpenAI-compatible API (needs OPENAI_API_KEY; optional OPENAI_BASE_URL)

Results are appended to results/runs.jsonl; finished (provider, model, condition, run, question)
rows are skipped on restart, so a stopped run can simply be started again.
"""
import argparse, json, os, re, threading, time
import duckdb, yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
CONDITIONS = ["schema", "tables", "lineage"]
TODAY = "2026-06-15"

SYSTEM = """You are a data agent for a battery manufacturing plant. You answer an engineer's question
by writing one DuckDB SQL query against the plant database described below.
Today is {today}.

Reply with JSON only, in one of two forms:
  {{"action": "sql", "sql": "<one read-only SELECT query>"}}
  {{"action": "clarify", "message": "<what you need to know or why the data cannot answer it>"}}
Use "clarify" only when the database cannot answer the question as asked.
The query result is the answer, so return just the numbers or rows asked for.

DATABASE SCHEMA
{ddl}
{extra}"""


def ddl(con):
    out = []
    for (t,) in con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main' ORDER BY 1").fetchall():
        cols = con.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name=? ORDER BY ordinal_position", [t]).fetchall()
        out.append(f"CREATE TABLE {t} (" + ", ".join(f"{c} {d}" for c, d in cols) + ");")
    return "\n".join(out)


def system_prompt(con, condition):
    extra = ""
    if condition in ("tables", "lineage"):
        extra += "\nTABLE METADATA (governed semantic layer)\n" + open(os.path.join(ROOT, "metadata", "tables.yaml")).read()
    if condition == "lineage":
        extra += "\nLINEAGE\n" + open(os.path.join(ROOT, "metadata", "lineage.yaml")).read()
    return SYSTEM.format(today=TODAY, ddl=ddl(con), extra=extra)


def run_sql(con, sql, timeout=30):
    if not re.match(r"^\s*(WITH|SELECT)\b", sql, re.I) or ";" in sql.strip().rstrip(";"):
        raise ValueError("only a single SELECT query is allowed")
    timer = threading.Timer(timeout, con.interrupt); timer.start()
    try:
        cur = con.execute(sql.strip().rstrip(";"))
        return [d[0] for d in cur.description], cur.fetchmany(10000)
    finally:
        timer.cancel()


# ---------- scoring ----------
def _num(v):
    if isinstance(v, bool) or v is None:
        return v
    try:
        return float(v)
    except (TypeError, ValueError):
        return str(v).strip()


def _eq(a, b):
    a, b = _num(a), _num(b)
    if isinstance(a, float) and isinstance(b, float):
        if abs(a - b) <= 1e-4 * max(1.0, abs(b)):
            return True
        return 0 < abs(b) <= 1 and abs(a - 100 * b) <= 1e-2   # yield as a percent
    return str(a) == str(b)


def _rows_match(pred_rows, gold_rows):
    if len(pred_rows) != len(gold_rows):
        return False
    key = lambda r: tuple(str(round(x, 3)) if isinstance(x, float) else str(x) for x in map(_num, r))
    p, g = sorted(pred_rows, key=key), sorted(gold_rows, key=key)
    if all(all(_eq(x, y) for x, y in zip(pr, gr)) for pr, gr in zip(p, g)):
        return True
    # fall back to unordered row matching (sorting can differ when a percent is used)
    left = list(pred_rows)
    for gr in gold_rows:
        hit = next((i for i, pr in enumerate(left) if all(_eq(x, y) for x, y in zip(pr, gr))), None)
        if hit is None:
            return False
        left.pop(hit)
    return True


def match(pred_cols, pred_rows, gold_rows):
    """Correct if some ordered subset of the predicted columns equals the gold result (any row order)."""
    if not gold_rows:
        return not pred_rows
    k = len(gold_rows[0])
    n = len(pred_cols)
    if n < k or n > 8:
        return False
    import itertools
    for idx in itertools.permutations(range(n), k):
        if _rows_match([tuple(r[i] for i in idx) for r in pred_rows], gold_rows):
            return True
    return False


# ---------- providers ----------
def parse_reply(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {"action": "sql", "sql": text.strip().strip("`")}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        s = re.search(r'"sql"\s*:\s*"(.*)"', m.group(0), re.S)
        return {"action": "sql", "sql": s.group(1).encode().decode("unicode_escape")} if s else {"action": "clarify", "message": "unparseable"}


class LLM:
    def __init__(self, provider, model):
        self.provider, self.model = provider, model
        if provider == "anthropic":
            import anthropic
            self.client = anthropic.Anthropic()
        elif provider == "openai":
            import openai
            self.client = openai.OpenAI(base_url=os.environ.get("OPENAI_BASE_URL") or None)

    def ask(self, system, messages):
        for attempt in range(5):
            try:
                if self.provider == "anthropic":
                    # Opus 5.5 / Haiku 5.5 reject sampling params (temperature); effort is set explicitly instead.
                    r = self.client.messages.create(model=self.model, max_tokens=16000,
                                                    output_config={"effort": os.environ.get("EFFORT", "medium")},
                                                    system=system, messages=messages)
                    return "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
                r = self.client.chat.completions.create(model=self.model, temperature=0,
                                                        messages=[{"role": "system", "content": system}] + messages)
                return r.choices[0].message.content
            except Exception as e:  # rate limits, timeouts
                if attempt == 4:
                    raise
                time.sleep(2 ** attempt * 5)


def answer(provider, llm, system, q, con):
    """Returns (decision, sql, cols, rows, error, n_calls)."""
    if provider in ("oracle", "naive"):
        sql = q["gold"] if provider == "oracle" else q["naive"]
        if sql is None:
            return ("clarify", None, None, None, None, 0) if provider == "oracle" else ("sql", "SELECT 0 AS value", ["value"], [(0,)], None, 0)
        cols, rows = run_sql(con, sql)
        return "sql", sql, cols, rows, None, 0
    msgs = [{"role": "user", "content": q["q"]}]
    text = llm.ask(system, msgs); calls = 1
    rep = parse_reply(text)
    if rep.get("action") == "clarify":
        return "clarify", None, None, None, None, calls
    sql = rep.get("sql", "")
    try:
        cols, rows = run_sql(con, sql)
        return "sql", sql, cols, rows, None, calls
    except Exception as e:  # one repair attempt
        msgs += [{"role": "assistant", "content": text},
                 {"role": "user", "content": f"The query failed with this error: {e}\nReply with corrected JSON."}]
        text = llm.ask(system, msgs); calls += 1
        rep = parse_reply(text)
        if rep.get("action") == "clarify":
            return "clarify", None, None, None, None, calls
        sql = rep.get("sql", "")
        try:
            cols, rows = run_sql(con, sql)
            return "sql", sql, cols, rows, None, calls
        except Exception as e2:
            return "error", sql, None, None, str(e2)[:300], calls


def score(q, decision, cols, rows, gold_rows):
    if q["gold"] is None:                      # unanswerable question
        return ("correct", None) if decision == "clarify" else ("silent_wrong", q["trap"]) if decision == "sql" else ("error", q["trap"])
    if decision == "clarify":
        return "clarified", None
    if decision == "error":
        return "error", "execution"
    return ("correct", None) if match(cols, rows, gold_rows) else ("silent_wrong", q["trap"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", required=True, choices=["oracle", "naive", "anthropic", "openai"])
    ap.add_argument("--model", default="-")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--conditions", default=",".join(CONDITIONS))
    ap.add_argument("--db", default=os.path.join(ROOT, "data", "factory.duckdb"))
    ap.add_argument("--questions", default=os.path.join(ROOT, "questions.jsonl"))
    ap.add_argument("--out", default=os.path.join(ROOT, "results", "runs.jsonl"))
    ap.add_argument("--limit", type=int, default=0, help="only the first N questions (for a quick check)")
    a = ap.parse_args()

    qs = [json.loads(l) for l in open(a.questions)]
    if a.limit:
        qs = qs[:a.limit]
    con = duckdb.connect(a.db, read_only=True)
    gold = {q["id"]: run_sql(con, q["gold"])[1] for q in qs if q["gold"]}
    llm = LLM(a.provider, a.model) if a.provider in ("anthropic", "openai") else None
    runs = 1 if a.provider in ("oracle", "naive") else a.runs

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    done = set()
    if os.path.exists(a.out):
        for l in open(a.out):
            r = json.loads(l); done.add((r["provider"], r["model"], r["condition"], r["run"], r["qid"]))
    with open(a.out, "a") as f:
        for cond in a.conditions.split(","):
            system = system_prompt(con, cond)
            for run in range(1, runs + 1):
                for q in qs:
                    key = (a.provider, a.model, cond, run, q["id"])
                    if key in done:
                        continue
                    t0 = time.time()
                    try:
                        dec, sql, cols, rows, err, calls = answer(a.provider, llm, system, q, con)
                    except Exception as e:
                        dec, sql, cols, rows, err, calls = "error", None, None, None, str(e)[:300], 0
                    outcome, etype = score(q, dec, cols, rows, gold.get(q["id"]))
                    rec = dict(provider=a.provider, model=a.model, condition=cond, run=run, qid=q["id"],
                               cat=q["cat"], trap=q["trap"], decision=dec, outcome=outcome, error_type=etype,
                               sql=sql, result=[list(map(str, r)) for r in rows[:5]] if rows else None,
                               error=err, calls=calls, secs=round(time.time() - t0, 2))
                    f.write(json.dumps(rec) + "\n"); f.flush()
                    print(f"{cond:8s} run{run} {q['id']} {q['cat']:10s} {outcome}")


if __name__ == "__main__":
    main()
