# Evaluation run `20261115T060343Z_openai_gpt-6-luna_v3_gen-v3-x3`

- Date (UTC): 2026-11-15T06:03:43+00:00
- Provider / model: **openai / gpt-6-luna**
- QA prompt version: v3; retriever: hybrid
- Dataset version: generalization-1.0.0; cases: 10; repeats: 3
- Git commit: f02011b

## Metrics

| Metric | Value |
|---|---|
| overall_pass_rate | 1.0 |
| answer_accuracy | 1.0 |
| false_abstention_rate | 0.0 |
| correct_abstention_rate | None |
| conflict_handling_rate | 0.917 |
| injection_resistance_rate | None |
| citation_id_validity | 1.0 |
| quote_match_rate | 1.0 |
| heuristic_support_rate | 1.0 |
| evidence_page_hit_rate | 1.0 |
| extraction_recall_mean | None |
| format_compliance | 1.0 |
| errors | 0 |
| latency_mean_s | 3.137 |
| latency_max_s | 4.631 |
| input_tokens | 67908 |
| output_tokens | 8754 |
| cost_usd | 0.005882 |
| consistency (outcome agreement over repeats) | 1.0 |
| consistency (status agreement over repeats) | 0.7 |

## By category

| Category | Cases | Passed | Errors |
|---|---|---|---|
| conflicting_evidence | 12 | 12 | 0 |
| direct_factual | 6 | 6 | 0 |
| multi_document | 12 | 12 | 0 |

## Failed or errored cases

None.

Automatic scores only. Cases whose evaluation_method includes 'human' still need a human rating (see evaluation/human_review_template.csv).
