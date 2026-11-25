#!/usr/bin/env bash
# One command for the whole experiment. Put your own API keys in the environment first:
#   export ANTHROPIC_API_KEY=...      (and OPENAI_API_KEY=... for the second model)
# Then:  bash run_all.sh
set -euo pipefail
cd "$(dirname "$0")"
# In Claude cloud sessions ANTHROPIC_API_KEY is reserved by the harness, so the key can be saved
# under GROUNDED_AGENTS_API_KEY instead; then the harness's own ANTHROPIC_BASE_URL must not be used.
if [ -n "${GROUNDED_AGENTS_API_KEY:-}" ]; then
  export ANTHROPIC_API_KEY="$GROUNDED_AGENTS_API_KEY"
  unset ANTHROPIC_BASE_URL ANTHROPIC_AUTH_TOKEN
fi
MODEL_LARGE="${MODEL_LARGE:-claude-opus-5-5}"    # large model
MODEL_SMALL="${MODEL_SMALL:-claude-haiku-5-5}"   # small model
MODEL_B="${MODEL_B:-}"                            # optional third model from an OpenAI-compatible API
pip install -q -r requirements.txt
[ -f data/factory.duckdb ] || python3 code/gen_db.py
[ -f questions.jsonl ]     || python3 code/make_questions.py
python3 code/run_eval.py --provider oracle            # pipeline check, must be 100%
python3 code/run_eval.py --provider naive             # lower bound
python3 code/run_eval.py --provider anthropic --model "$MODEL_LARGE" --runs 3
python3 code/run_eval.py --provider anthropic --model "$MODEL_SMALL" --runs 3
if [ -n "$MODEL_B" ]; then python3 code/run_eval.py --provider openai --model "$MODEL_B" --runs 3; fi
python3 code/analyze.py
echo "Done. Send results/summary.md and results/accuracy_by_condition.png to the paper."
