"""Generate the question set with gold SQL (governed answer) and a naive SQL
(the plausible wrong answer an ungrounded agent tends to write).

A question is kept only if its gold answer is non-empty and differs from the
naive answer, so every kept question actually tests a trap.
The naive SQL is used only for this check and is never shown to the agent.

Usage: python make_questions.py --db ../data/factory.duckdb --out ../questions.jsonl
"""
import argparse
import json
import os
import random

import duckdb

LAST_WEEK = ("2026-06-08", "2026-06-15")  # local Monday..Sunday before "today" (2026-06-15)
MONTHS = {"March 2026": ("2026-03-01", "2026-04-01"), "April 2026": ("2026-04-01", "2026-05-01"),
          "May 2026": ("2026-05-01", "2026-06-01")}

LOCAL_BLD = "(p.bld_ts_utc + to_hours(CAST(si.utc_ofst_h AS BIGINT)))"
PACK_SITE = "pk_bld p JOIN dim_ln l ON l.ln_id = p.ln_id JOIN dim_site si ON si.site_id = l.site_id"
LOCAL_TST = "(t.tst_ts_utc + to_hours(CAST(si.utc_ofst_h AS BIGINT)))"
TST_SITE = "tst_rslt t JOIN dim_ln l ON l.ln_id = t.ln_id JOIN dim_site si ON si.site_id = l.site_id"
LOCAL_SCR = "(s.scrp_ts_utc + to_hours(CAST(si.utc_ofst_h AS BIGINT)))"
SCR_SITE = "scrp_evt s JOIN dim_ln l ON l.ln_id = s.ln_id JOIN dim_site si ON si.site_id = l.site_id"
GOV_SCR = "s.lvl = 'PACK' AND s.eng_flg = 0 AND s.vd_flg = 0"


def rng_where(expr, a, b):
    return f"{expr} >= TIMESTAMP '{a}' AND {expr} < TIMESTAMP '{b}'"


def q_genealogy(con):
    out = []
    # lots that lost cells through rework
    lots = [r[0] for r in con.execute("""
        SELECT c.lot_id FROM rwk_evt r JOIN gnl_lnk g ON g.parent_sn = r.old_sn AND g.child_lvl='CELL'
        JOIN cel_mst c ON c.cell_sn = g.child_sn GROUP BY 1 ORDER BY count(*) DESC, 1 LIMIT 12""").fetchall()]
    for L in lots:
        gold = f"""SELECT COUNT(DISTINCT pm.parent_sn) AS packs
FROM cel_mst c
JOIN gnl_lnk cm ON cm.child_sn = c.cell_sn AND cm.child_lvl = 'CELL' AND cm.vld_to IS NULL
JOIN gnl_lnk pm ON pm.child_sn = cm.parent_sn AND pm.child_lvl = 'MOD' AND pm.vld_to IS NULL
WHERE c.lot_id = {L}"""
        naive = gold.replace(" AND cm.vld_to IS NULL", "").replace(" AND pm.vld_to IS NULL", "")
        out.append(dict(cat="genealogy", trap="keys_join_paths",
                        q=f"How many packs currently contain at least one cell from lot {L}?", gold=gold, naive=naive))
    sup = [(r[0], r[1]) for r in con.execute("""
        SELECT l.supp_id, p.ln_id FROM rwk_evt r JOIN gnl_lnk g ON g.parent_sn = r.old_sn AND g.child_lvl='CELL'
        JOIN cel_mst c ON c.cell_sn = g.child_sn JOIN dim_lot l ON l.lot_id = c.lot_id
        JOIN pk_bld p ON p.pack_sn = r.pack_sn GROUP BY 1,2 ORDER BY count(*) DESC, 1, 2 LIMIT 12""").fetchall()]
    for S, ln in sup:
        for mname, (a, b) in MONTHS.items():
            gold = f"""SELECT COUNT(DISTINCT p.pack_sn) AS packs
FROM {PACK_SITE}
JOIN gnl_lnk pm ON pm.parent_sn = p.pack_sn AND pm.child_lvl = 'MOD' AND pm.vld_to IS NULL
JOIN gnl_lnk cm ON cm.parent_sn = pm.child_sn AND cm.child_lvl = 'CELL' AND cm.vld_to IS NULL
JOIN cel_mst c ON c.cell_sn = cm.child_sn JOIN dim_lot lt ON lt.lot_id = c.lot_id
WHERE p.ln_id = {ln} AND lt.supp_id = {S} AND {rng_where(LOCAL_BLD, a, b)}"""
            naive = (gold.replace(" AND pm.vld_to IS NULL", "").replace(" AND cm.vld_to IS NULL", "")
                     .replace(LOCAL_BLD, "p.bld_ts_utc"))
            out.append(dict(cat="genealogy", trap="keys_join_paths",
                            q=f"How many packs built on line {ln} in {mname} currently contain cells from supplier {S}?",
                            gold=gold, naive=naive))
    packs = [r[0] for r in con.execute("SELECT pack_sn FROM rwk_evt ORDER BY rwk_id LIMIT 40").fetchall()]
    for P in packs:
        gold = f"""SELECT DISTINCT c.lot_id
FROM gnl_lnk pm
JOIN gnl_lnk cm ON cm.parent_sn = pm.child_sn AND cm.child_lvl = 'CELL' AND cm.vld_to IS NULL
JOIN cel_mst c ON c.cell_sn = cm.child_sn
WHERE pm.parent_sn = '{P}' AND pm.child_lvl = 'MOD' AND pm.vld_to IS NULL"""
        naive = gold.replace(" AND cm.vld_to IS NULL", "").replace(" AND pm.vld_to IS NULL", "")
        out.append(dict(cat="genealogy", trap="keys_join_paths",
                        q=f"Which cell lots does pack {P} contain today? List the lot IDs.", gold=gold, naive=naive))
    return out


def q_temporal(con):
    out = []
    a, b = LAST_WEEK
    for ln in range(1, 7):
        gold = f"SELECT COUNT(*) AS packs FROM {PACK_SITE} WHERE p.ln_id = {ln} AND {rng_where(LOCAL_BLD, a, b)}"
        naive = f"SELECT COUNT(*) AS packs FROM pk_bld p WHERE p.ln_id = {ln} AND {rng_where('p.bld_ts_utc', a, b)}"
        out.append(dict(cat="temporal", trap="column_semantics",
                        q=f"How many packs were built on line {ln} last week?", gold=gold, naive=naive))
    for site in ["AUS", "BER"]:
        for d0, d1 in [("2026-05-04", "2026-05-05"), ("2026-05-19", "2026-05-20"), ("2026-06-02", "2026-06-03")]:
            gold = f"SELECT COUNT(*) AS packs FROM {PACK_SITE} WHERE si.site_cd = '{site}' AND {rng_where(LOCAL_BLD, d0, d1)}"
            naive = f"SELECT COUNT(*) AS packs FROM {PACK_SITE} WHERE si.site_cd = '{site}' AND {rng_where('p.bld_ts_utc', d0, d1)}"
            out.append(dict(cat="temporal", trap="column_semantics",
                            q=f"How many packs were built at the {site} site on {d0}?", gold=gold, naive=naive))
    return out


def q_retest(con):
    out = []
    a, b = LAST_WEEK
    for ln in range(1, 7):
        gold = f"""SELECT AVG(CASE WHEN t.rslt_cd = 'P' THEN 1.0 ELSE 0.0 END) AS fpy
FROM {TST_SITE} WHERE t.atmpt_no = 1 AND t.ln_id = {ln} AND {rng_where(LOCAL_TST, a, b)}"""
        naive = f"""SELECT AVG(CASE WHEN t.rslt_cd = 'P' THEN 1.0 ELSE 0.0 END) AS fpy
FROM tst_rslt t WHERE t.ln_id = {ln} AND {rng_where('t.tst_ts_utc', a, b)}"""
        out.append(dict(cat="retest", trap="governed_measures",
                        q=f"What was the first-pass yield at final test on line {ln} last week? Give it as a fraction between 0 and 1.",
                        gold=gold, naive=naive))
    latest = f"""WITH f AS (
  SELECT t.pack_sn, t.ln_id, {LOCAL_TST} AS first_lcl FROM {TST_SITE} WHERE t.atmpt_no = 1),
last AS (
  SELECT pack_sn, rslt_cd FROM tst_rslt QUALIFY ROW_NUMBER() OVER (PARTITION BY pack_sn ORDER BY atmpt_no DESC) = 1)"""
    for ln in range(1, 7):
        for mname, (ma, mb) in MONTHS.items():
            gold = f"""{latest}
SELECT COUNT(*) AS failed_packs FROM f JOIN last USING (pack_sn)
WHERE f.ln_id = {ln} AND last.rslt_cd = 'F' AND {rng_where('f.first_lcl', ma, mb)}"""
            naive = f"""SELECT COUNT(*) AS failed_packs FROM tst_rslt t
WHERE t.ln_id = {ln} AND t.rslt_cd = 'F' AND {rng_where('t.tst_ts_utc', ma, mb)}"""
            out.append(dict(cat="retest", trap="known_traps",
                            q=f"How many packs failed final test on line {ln} in {mname}?", gold=gold, naive=naive))
            gold_y = f"""{latest}
SELECT AVG(CASE WHEN last.rslt_cd = 'P' THEN 1.0 ELSE 0.0 END) AS final_yield FROM f JOIN last USING (pack_sn)
WHERE f.ln_id = {ln} AND {rng_where('f.first_lcl', ma, mb)}"""
            naive_y = f"""SELECT AVG(CASE WHEN t.rslt_cd = 'P' THEN 1.0 ELSE 0.0 END) AS final_yield FROM tst_rslt t
WHERE t.ln_id = {ln} AND {rng_where('t.tst_ts_utc', ma, mb)}"""
            out.append(dict(cat="retest", trap="governed_measures",
                            q=f"What was the final-test yield on line {ln} in {mname}? Give it as a fraction between 0 and 1.",
                            gold=gold_y, naive=naive_y))
    return out


def q_scrap(con):
    out = []
    a, b = LAST_WEEK
    wins = [("last week", a, b)] + [(m, x, y) for m, (x, y) in MONTHS.items()]
    for label, x, y in wins:
        for ln in range(1, 7):
            gold = f"SELECT COUNT(DISTINCT s.sn) AS scrapped_packs FROM {SCR_SITE} WHERE {GOV_SCR} AND s.ln_id = {ln} AND {rng_where(LOCAL_SCR, x, y)}"
            naive = f"SELECT COUNT(*) AS scrapped_packs FROM scrp_evt s WHERE s.ln_id = {ln} AND {rng_where('s.scrp_ts_utc', x, y)}"
            when = label if label == "last week" else f"in {label}"
            out.append(dict(cat="scrap", trap="known_traps",
                            q=f"How many packs were scrapped on line {ln} {when}?", gold=gold, naive=naive))
    for ln in range(1, 7):
        x, y = "2026-03-01", "2026-06-15"
        gold = f"""SELECT s.rsn_cd FROM {SCR_SITE} WHERE {GOV_SCR} AND s.ln_id = {ln} AND {rng_where(LOCAL_SCR, x, y)}
GROUP BY 1 ORDER BY COUNT(DISTINCT s.sn) DESC LIMIT 1"""
        naive = f"""SELECT s.rsn_cd FROM scrp_evt s WHERE s.ln_id = {ln} GROUP BY 1 ORDER BY COUNT(*) DESC LIMIT 1"""
        tie = con.execute(f"""SELECT COUNT(*) FROM (SELECT s.rsn_cd, COUNT(DISTINCT s.sn) n FROM {SCR_SITE}
            WHERE {GOV_SCR} AND s.ln_id = {ln} GROUP BY 1) WHERE n = (SELECT MAX(n) FROM (SELECT COUNT(DISTINCT s.sn) n
            FROM {SCR_SITE} WHERE {GOV_SCR} AND s.ln_id = {ln} GROUP BY s.rsn_cd))""").fetchone()[0]
        if tie == 1:
            out.append(dict(cat="scrap", trap="governed_measures",
                            q=f"What has been the most common scrap reason on line {ln} since March 1, 2026? Give the reason code.",
                            gold=gold, naive=naive))
    return out


def q_fresh(con):
    out = []
    for ln in range(1, 7):
        for mname, (x, y) in MONTHS.items():
            gold = f"SELECT SUM(scrp_cnt) AS scrapped_packs FROM agg_scrp_dly WHERE ln_id = {ln} AND dt_lcl >= DATE '{x}' AND dt_lcl < DATE '{y}'"
            naive = f"SELECT SUM(scrp_cnt) AS scrapped_packs FROM scrp_dly_snap WHERE ln_id = {ln} AND dt >= DATE '{x}' AND dt < DATE '{y}'"
            out.append(dict(cat="freshness", trap="lineage",
                            q=f"Using the daily scrap summary, what was the total scrap count on line {ln} for {mname}?",
                            gold=gold, naive=naive))
    return out


CLARIFY = [
    "What was the OEE on line 2 last week?",
    "What were the labor hours per pack on line 4 in May 2026?",
    "How many packs were shipped to customers last week?",
    "What was the total scrap cost on line 1 in April 2026?",
    "What was the energy consumption per pack at the BER site in May 2026?",
    "What is the takt time on line 5?",
]


def norm(rows):
    return sorted(tuple(round(v, 4) if isinstance(v, float) else v for v in r) for r in rows)


def main(db, out_path, per_cat):
    con = duckdb.connect(db, read_only=True)
    pools = {"genealogy": q_genealogy(con), "temporal": q_temporal(con), "retest": q_retest(con),
             "scrap": q_scrap(con), "freshness": q_fresh(con)}
    kept = []
    for cat, qs in pools.items():
        random.Random(7).shuffle(qs)  # mix templates within a category
        n = 0
        for q in qs:
            g = con.execute(q["gold"]).fetchall()
            nv = con.execute(q["naive"]).fetchall()
            if not g or g == [(None,)] or g == [(0,)] or norm(g) == norm(nv):
                continue
            kept.append(q); n += 1
            if n >= per_cat[cat]:
                break
        print(f"{cat}: kept {n} of {len(qs)} candidates")
    for q in CLARIFY:
        kept.append(dict(cat="clarify", trap="governed_measures", q=q, gold=None, naive=None))
    with open(out_path, "w") as f:
        for i, q in enumerate(kept, 1):
            q["id"] = f"Q{i:02d}"
            f.write(json.dumps(q) + "\n")
    print(f"wrote {len(kept)} questions to {out_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    here = os.path.dirname(__file__)
    ap.add_argument("--db", default=os.path.join(here, "..", "data", "factory.duckdb"))
    ap.add_argument("--out", default=os.path.join(here, "..", "questions.jsonl"))
    a = ap.parse_args()
    main(a.db, a.out, {"genealogy": 16, "temporal": 10, "retest": 12, "scrap": 10, "freshness": 6})
