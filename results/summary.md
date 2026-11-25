# Results

Accuracy = share of questions answered correctly (for the 6 unanswerable questions, correct means the agent asked to clarify).
Silent wrong = the agent returned an answer and it was wrong. Clarified = the agent asked instead of answering an answerable question.
Numbers are means over runs; each cell is a percent of questions.

## Overall

| System | Condition | Accuracy | Silent wrong | Clarified | Error | N |
|---|---|---|---|---|---|---|
| claude-haiku-5-5 | schema | 39.4 | 41.1 | 18.9 | 0.6 | 180 |
| claude-haiku-5-5 | tables | 96.7 | 3.3 | 0.0 | 0.0 | 180 |
| claude-haiku-5-5 | lineage | 96.7 | 3.3 | 0.0 | 0.0 | 180 |
| claude-opus-5-5 | schema | 90.6 | 9.4 | 0.0 | 0.0 | 180 |
| claude-opus-5-5 | tables | 100.0 | 0.0 | 0.0 | 0.0 | 180 |
| claude-opus-5-5 | lineage | 100.0 | 0.0 | 0.0 | 0.0 | 180 |

## Accuracy by question category

| System | Condition | clarify | freshness | genealogy | retest | scrap | temporal |
|---|---|---|---|---|---|---|---|
| claude-haiku-5-5 | schema | 100.0 | 100.0 | 0.0 | 0.0 | 33.3 | 83.3 |
| claude-haiku-5-5 | tables | 100.0 | 100.0 | 100.0 | 100.0 | 80.0 | 100.0 |
| claude-haiku-5-5 | lineage | 100.0 | 100.0 | 97.9 | 100.0 | 83.3 | 100.0 |
| claude-opus-5-5 | schema | 100.0 | 100.0 | 100.0 | 86.1 | 60.0 | 100.0 |
| claude-opus-5-5 | tables | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |
| claude-opus-5-5 | lineage | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |

## Silent-wrong answers by error type (Table I category)

| System | Condition | Error type | Count |
|---|---|---|---|
| claude-haiku-5-5 | schema | keys_join_paths | 47 |
| claude-haiku-5-5 | schema | governed_measures | 11 |
| claude-haiku-5-5 | schema | known_traps | 11 |
| claude-haiku-5-5 | schema | column_semantics | 5 |
| claude-haiku-5-5 | tables | governed_measures | 6 |
| claude-haiku-5-5 | lineage | governed_measures | 5 |
| claude-haiku-5-5 | lineage | keys_join_paths | 1 |
| claude-opus-5-5 | schema | governed_measures | 12 |
| claude-opus-5-5 | schema | known_traps | 5 |
