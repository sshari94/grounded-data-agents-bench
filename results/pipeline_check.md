# Results

Accuracy = share of questions answered correctly (for the 6 unanswerable questions, correct means the agent asked to clarify).
Silent wrong = the agent returned an answer and it was wrong. Clarified = the agent asked instead of answering an answerable question.
Numbers are means over runs; each cell is a percent of questions.

## Overall

| System | Condition | Accuracy | Silent wrong | Clarified | Error | N |
|---|---|---|---|---|---|---|
| naive - | schema | 0.0 | 100.0 | 0.0 | 0.0 | 60 |
| naive - | tables | 0.0 | 100.0 | 0.0 | 0.0 | 60 |
| naive - | lineage | 0.0 | 100.0 | 0.0 | 0.0 | 60 |
| oracle - | schema | 100.0 | 0.0 | 0.0 | 0.0 | 60 |
| oracle - | tables | 100.0 | 0.0 | 0.0 | 0.0 | 60 |
| oracle - | lineage | 100.0 | 0.0 | 0.0 | 0.0 | 60 |

## Accuracy by question category

| System | Condition | clarify | freshness | genealogy | retest | scrap | temporal |
|---|---|---|---|---|---|---|---|
| naive - | schema | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| naive - | tables | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| naive - | lineage | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| oracle - | schema | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |
| oracle - | tables | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |
| oracle - | lineage | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |

## Silent-wrong answers by error type (Table I category)

| System | Condition | Error type | Count |
|---|---|---|---|
| naive - | schema | keys_join_paths | 16 |
| naive - | schema | governed_measures | 15 |
| naive - | schema | known_traps | 13 |
| naive - | schema | column_semantics | 10 |
| naive - | schema | lineage | 6 |
| naive - | tables | keys_join_paths | 16 |
| naive - | tables | governed_measures | 15 |
| naive - | tables | known_traps | 13 |
| naive - | tables | column_semantics | 10 |
| naive - | tables | lineage | 6 |
| naive - | lineage | keys_join_paths | 16 |
| naive - | lineage | governed_measures | 15 |
| naive - | lineage | known_traps | 13 |
| naive - | lineage | column_semantics | 10 |
| naive - | lineage | lineage | 6 |
