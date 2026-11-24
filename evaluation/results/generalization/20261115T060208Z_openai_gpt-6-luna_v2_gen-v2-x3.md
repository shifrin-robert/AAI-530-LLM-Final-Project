# Evaluation run `20261115T060208Z_openai_gpt-6-luna_v2_gen-v2-x3`

- Date (UTC): 2026-11-15T06:02:08+00:00
- Provider / model: **openai / gpt-6-luna**
- QA prompt version: v2; retriever: hybrid
- Dataset version: generalization-1.0.0; cases: 10; repeats: 3
- Git commit: f02011b

## Metrics

| Metric | Value |
|---|---|
| overall_pass_rate | 0.867 |
| answer_accuracy | 0.867 |
| false_abstention_rate | 0.0 |
| correct_abstention_rate | None |
| conflict_handling_rate | 0.5 |
| injection_resistance_rate | None |
| citation_id_validity | 1.0 |
| quote_match_rate | 1.0 |
| heuristic_support_rate | 0.958 |
| evidence_page_hit_rate | 1.0 |
| extraction_recall_mean | None |
| format_compliance | 1.0 |
| errors | 0 |
| latency_mean_s | 3.477 |
| latency_max_s | 5.592 |
| input_tokens | 64308 |
| output_tokens | 7659 |
| cost_usd | 0.005277 |
| consistency (outcome agreement over repeats) | 0.8 |
| consistency (status agreement over repeats) | 1.0 |

## By category

| Category | Cases | Passed | Errors |
|---|---|---|---|
| conflicting_evidence | 12 | 8 | 0 |
| direct_factual | 6 | 6 | 0 |
| multi_document | 12 | 12 | 0 |

## Failed or errored cases

- **GEN-01** (conflicting_evidence): missing facts [['640,000']]
- **GEN-02** (conflicting_evidence): missing facts [['61,750']]
- **GEN-01** (conflicting_evidence): missing facts [['640,000']]
- **GEN-02** (conflicting_evidence): missing facts [['61,750']]

Automatic scores only. Cases whose evaluation_method includes 'human' still need a human rating (see evaluation/human_review_template.csv).
