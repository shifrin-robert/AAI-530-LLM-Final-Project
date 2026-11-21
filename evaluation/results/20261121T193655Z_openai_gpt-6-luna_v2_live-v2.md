# Evaluation run `20261121T193655Z_openai_gpt-6-luna_v2_live-v2`

- Date (UTC): 2026-11-21T19:36:55+00:00
- Provider / model: **openai / gpt-6-luna**
- QA prompt version: v2; retriever: hybrid
- Dataset version: 1.0.0; cases: 40; repeats: 1
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
| quote_match_rate | 1.0 |
| heuristic_support_rate | 0.95 |
| evidence_page_hit_rate | 1.0 |
| extraction_recall_mean | 1.0 |
| format_compliance | 1.0 |
| errors | 0 |
| latency_mean_s | 3.662 |
| latency_max_s | 15.75 |
| input_tokens | 88170 |
| output_tokens | 16891 |
| cost_usd | 0.012847 |

## By category

| Category | Cases | Passed | Errors |
|---|---|---|---|
| ambiguous | 2 | 2 | 0 |
| comparison | 2 | 2 | 0 |
| conflicting_evidence | 3 | 3 | 0 |
| direct_factual | 8 | 8 | 0 |
| extraction | 2 | 2 | 0 |
| missing_information | 5 | 5 | 0 |
| multi_document | 4 | 4 | 0 |
| multi_page | 4 | 4 | 0 |
| numerical | 4 | 4 | 0 |
| prompt_injection | 4 | 4 | 0 |
| summarization | 2 | 2 | 0 |

## Failed or errored cases

None.

Automatic scores only. Cases whose evaluation_method includes 'human' still need a human rating (see evaluation/human_review_template.csv).
