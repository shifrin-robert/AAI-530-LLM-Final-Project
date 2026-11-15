# Evaluation run `20261114T203837Z_openai_gpt-6-luna_v2_live-v2`

- Date (UTC): 2026-11-14T20:38:37+00:00
- Provider / model: **openai / gpt-6-luna**
- QA prompt version: v2; retriever: hybrid
- Dataset version: 1.0.0; cases: 40; repeats: 1
- Git commit: a05820a

## Metrics

| Metric | Value |
|---|---|
| overall_pass_rate | 0.975 |
| answer_accuracy | 0.962 |
| false_abstention_rate | 0.0 |
| correct_abstention_rate | 1.0 |
| conflict_handling_rate | 0.333 |
| injection_resistance_rate | 1.0 |
| citation_id_validity | 1.0 |
| quote_match_rate | 1.0 |
| heuristic_support_rate | 0.964 |
| evidence_page_hit_rate | 1.0 |
| extraction_recall_mean | 1.0 |
| format_compliance | 1.0 |
| errors | 0 |
| latency_mean_s | 3.903 |
| latency_max_s | 17.776 |
| input_tokens | 88170 |
| output_tokens | 16517 |
| cost_usd | 0.01266 |

## By category

| Category | Cases | Passed | Errors |
|---|---|---|---|
| ambiguous | 2 | 2 | 0 |
| comparison | 2 | 2 | 0 |
| conflicting_evidence | 3 | 2 | 0 |
| direct_factual | 8 | 8 | 0 |
| extraction | 2 | 2 | 0 |
| missing_information | 5 | 5 | 0 |
| multi_document | 4 | 4 | 0 |
| multi_page | 4 | 4 | 0 |
| numerical | 4 | 4 | 0 |
| prompt_injection | 4 | 4 | 0 |
| summarization | 2 | 2 | 0 |

## Failed or errored cases

- **CF-02** (conflicting_evidence): missing facts [['112,400']]

Automatic scores only. Cases whose evaluation_method includes 'human' still need a human rating (see evaluation/human_review_template.csv).
