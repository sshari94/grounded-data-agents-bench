# Grounded data agents: experiment kit

This kit produces the evaluation section of "Grounded Artificial Intelligence Data Agents for
Manufacturing". It tests one claim from the paper: giving an LLM data agent a governed grounding
layer (table metadata, then lineage) reduces wrong answers on factory data questions, and most of
all reduces **silent wrong answers**, where the agent returns a confident number that is wrong.

## What is in it

| Path | What it is |
|---|---|
| `code/gen_db.py` | Builds `data/factory.duckdb`, a synthetic battery plant (2 sites, 6 lines, Mar 1 to Jun 14 2026). No real company data. |
| `code/make_questions.py` | Writes `questions.jsonl`: 60 engineer-style questions with a gold SQL answer and a "naive" SQL answer. |
| `metadata/tables.yaml` | The grounding layer, organised by the paper's Table I categories. |
| `metadata/lineage.yaml` | Lineage, added in the third condition only. |
| `code/run_eval.py` | Asks each question under three conditions and scores the answers. |
| `code/analyze.py` | Writes `results/summary.md` and `results/accuracy_by_condition.png`. |
| `run_all.sh` | Runs everything. |

### The traps the database contains (all realistic for battery manufacturing)
- Terse column names (`pk_bld`, `bld_ts_utc`, `vd_flg`).
- Genealogy is effective-dated: rework swaps modules, old links stay with `vld_to` set, and cell to pack is two hops.
- Final test has retests, so rows are attempts, not packs. First-pass yield and final yield differ.
- Scrap postings include voided duplicates, engineering samples and module scrap from rework.
- Timestamps are UTC, but "last week" and "in April" are plant-local time (one site is UTC-5, one is UTC+2).
- A legacy daily scrap snapshot stopped updating on 2026-03-31 and uses an old definition.
- Six questions ask for data the database does not hold (OEE, labour hours, cost, energy, shipments, takt). The right behaviour is to ask, not to guess.

A question was kept only when the gold answer and the naive answer give different results, so every
question tests one trap. Question categories: genealogy 16, time 10, retest 12, scrap 10, freshness 6, unanswerable 6.

### Conditions
1. `schema`: table definitions only.
2. `tables`: plus `metadata/tables.yaml`.
3. `lineage`: plus `metadata/lineage.yaml`.

Each model runs every question in every condition 3 times. Claude Opus 5.5 and Claude Haiku 5.5 do not accept a temperature setting, so every call uses the same fixed reasoning effort (`medium`, set with `EFFORT`); the 3 runs measure run-to-run variation. When a query fails, the
error is shown to the model once and it may correct it.

### Scoring
- **Correct**: the query result matches the gold result (row order ignored; extra columns allowed;
  4-decimal tolerance; a yield given as a percent counts). For the 6 unanswerable questions, correct
  means the agent asked to clarify.
- **Silent wrong**: the agent answered and the answer was wrong. Each is tagged with the Table I
  category of the trap the question tests, which gives the error breakdown table.
- **Clarified**: the agent asked instead of answering an answerable question (not counted as wrong, reported separately).
- **Error**: the query still failed after one correction.

## How to run

Use your own API key, in your own terminal. Never paste it into a chat or a document.

```bash
cd experiment
export ANTHROPIC_API_KEY=your-key
# defaults: a large and a small Claude model (change with MODEL_LARGE / MODEL_SMALL)
# optional third model from another provider:
# export OPENAI_API_KEY=your-key; export MODEL_B=<model name>
bash run_all.sh
```

The key comparison is the small model with metadata against the large model without it.

About 540 model calls per model (60 questions x 3 conditions x 3 runs), each with a prompt of
roughly 0.5k to 2.5k tokens. If it stops, run it again: finished answers are skipped.

`results/runs.jsonl` keeps every question, SQL query, result and score, so any number in the paper can be traced.

## Pipeline check (done Nov 24, 2026)
- `oracle` (gold SQL): 100% correct in all 3 conditions.
- `naive` (schema-only SQL): 0% correct, by construction.
- A simulated model whose first query fails and whose second is correct was scored correctly, so the repair path works.

## Limits to state in the paper
- The database is synthetic and the questions were written for this study to mirror the questions
  plant engineers ask; they were not collected from real engineers.
- The kit was built with AI coding assistance. The author reviewed the questions and gold answers,
  ran the experiment and checked the results; say this in the AI disclosure.
- 60 questions, 2 models, 1 database. Report means and the spread across the 3 runs.
- The naive baseline is 0% by construction (questions were filtered so naive SQL fails); report it
  as a check, not as a finding.
