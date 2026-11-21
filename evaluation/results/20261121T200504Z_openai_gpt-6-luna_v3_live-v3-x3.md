# Evaluation run `20261121T200504Z_openai_gpt-6-luna_v3_live-v3-x3`

- Date (UTC): 2026-11-21T20:05:04+00:00
- Provider / model: **openai / gpt-6-luna**
- QA prompt version: v3; retriever: hybrid
- Dataset version: 1.0.0; cases: 40; repeats: 3
- Git commit: 6a93cee

## Metrics

| Metric | Value |
|---|---|
| overall_pass_rate | 1.0 |
| answer_accuracy | 1.0 |
| false_abstention_rate | 0.0 |
| correct_abstention_rate | 1.0 |
| conflict_handling_rate | 0.667 |
| injection_resistance_rate | 1.0 |
| citation_id_validity | 1.0 |
| quote_match_rate | 0.993 |
| heuristic_support_rate | 0.952 |
| evidence_page_hit_rate | 1.0 |
| extraction_recall_mean | 1.0 |
| format_compliance | 1.0 |
| errors | 0 |
| latency_mean_s | 4.111 |
| latency_max_s | 24.07 |
| input_tokens | 288666 |
| output_tokens | 53210 |
| cost_usd | 0.032715 |
| consistency (outcome agreement over repeats) | 1.0 |
| consistency (status agreement over repeats) | 0.975 |

## By category

| Category | Cases | Passed | Errors |
|---|---|---|---|
| ambiguous | 6 | 6 | 0 |
| comparison | 6 | 6 | 0 |
| conflicting_evidence | 9 | 9 | 0 |
| direct_factual | 24 | 24 | 0 |
| extraction | 6 | 6 | 0 |
| missing_information | 15 | 15 | 0 |
| multi_document | 12 | 12 | 0 |
| multi_page | 12 | 12 | 0 |
| numerical | 12 | 12 | 0 |
| prompt_injection | 12 | 12 | 0 |
| summarization | 6 | 6 | 0 |

## Failed or errored cases

None.

Automatic scores only. Cases whose evaluation_method includes 'human' still need a human rating (see evaluation/human_review_template.csv).
