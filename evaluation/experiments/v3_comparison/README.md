# Experiment: comparing the two prompt v3 proposals

**Status: experimental, run on 2026-11-24.**

- **Nothing in the app changed.** The app's prompts, default prompt and scoring are as they were.
- **Neither pull request is merged.**
- **Scores are automatic.** No answer here has been reviewed by a person.

Two pull requests each propose a different file as `prompts/grounded_qa_v3.md`, and both make it the
default. This folder compares the two under the same conditions. Both files call themselves
`grounded_qa@v3`, so this experiment gives each one a temporary name.

| Name | Pull request | Evaluated file | Instructions SHA-256 |
|---|---|---|---|
| `robert_v3` | 2 (`byok-authentication`) | `prompts/grounded_qa_v3.md` at `f02011b` (blob `1489b78`) | `c6a5feecb14f…` |
| `josue_v3` | 1 (`josue/fix-windows-encoding`) | `prompts/grounded_qa_v3.md` at `b0dc869` (blob `90197b3`) | `725c73c047a1…` |

`josue_v3` was proposed by Josue Sandoval in PR #1, and `robert_v3` by Robert Shifrin in PR #2.
Both are copied here unchanged, for comparison only.

The instructions hash is the one `tests/test_prompting.py` pins: the SHA-256 of the system and user
sections. Full hashes, commits and blobs are in [manifest.json](manifest.json). Byte-identical
copies of both files are in `prompts/`.

## What differs

Both prompts are prompt v2 with only the header and section 7 ("Conflicting evidence") changed.
Every other v2 section is identical in both, including the injection defences.

- **`robert_v3`** keeps v2's section 7 and adds one rule. A figure that changes over time and is
  reported as of different dates is given with every value, date and citation, most recent first,
  and treated as a context difference.
- **`josue_v3`** rewrites section 7:
  - it checks first whether more than one source gives a value;
  - it treats any different values for the same thing as conflicting evidence, "even when one
    source is newer or the difference is explained by 'as of' dates, versions or scope": status
    `conflicting_evidence`, every version stated, none dropped;
  - it makes an exception when a source says which version prevails: status `answered`, with the
    replaced value named;
  - it requires the fields to agree: if `conflicts[]` is not empty, the status must be
    `conflicting_evidence`;
  - it says that sources giving the same value agree;
  - it narrows `context_difference` to "as of" dates of a figure that changes over time, and gives
    "two different planned dates for the same event" as an example of `direct_contradiction`.

## Method

- **Run:** `josue_v3` was run on the 10-case generalization set (`evaluation/generalization/`),
  3 times per case, with `gpt-6-luna`, by [run_josue_v3.py](run_josue_v3.py).
- **The harness:** it runs the unchanged evaluation runner. It serves `josue_v3` from its copy in
  this process only, after checking the copy's file hash and instructions hash. An offline mock
  run beforehand confirmed that the prompt was served to 30 of 30 case runs.
- **Same conditions as the earlier runs** of v2 and `robert_v3` on 2026-11-15, checked before the
  paid run:
  - model, hybrid retrieval and all eight recorded settings (reasoning effort, token budgets,
    chunking, top-k);
  - Python and SDK versions;
  - cases, reference answers, documents and scorer.
- **Nothing changed after the results were seen.** The reference answers and scoring rules stayed
  as they were.
- **Scoring:** the original scorer, plus the proposed revised rules (`evaluation/scoring_audit.py`)
  for the three runs, written to `audit/`.
- **Cost:** the free estimate was $0.0405. The authorization was up to $0.10, and the run cost
  $0.006151.
- **Provenance:** recorded in `results/*.provenance.json`:
  - commit `2a7f747`, with no other changes in the tree;
  - the hashes of the prompt, the runner, the harness, the cases and the documents.

## Results on the generalization set

| Measure | v2 | `robert_v3` | `josue_v3` |
|---|---|---|---|
| Case runs passed, original / revised scoring | 26 / 26 of 30 | 30 / 30 of 30 | 30 / 30 of 30 |
| Figures reported on different dates (GEN-01, GEN-02) | 2 / 6 | 6 / 6 | 6 / 6 |
| … status `conflicting_evidence` | 0 / 6 | 3 / 6 | 6 / 6 |
| Current and historical figure (GEN-03, GEN-04) | 6 / 6 | 6 / 6 | 6 / 6 |
| … last year's figure mentioned or flagged | 0 / 6 | 0 / 6 | 0 / 6 |
| Revised and original budget (GEN-05, GEN-06) | 6 / 6 | 6 / 6 | 6 / 6 |
| … replaced budget named | 3 / 6 | 5 / 6 | 6 / 6 |
| Compatible figures (GEN-07, GEN-08), conflicts flagged | 0 / 6 | 0 / 6 | 0 / 6 |
| Genuine contradictions (GEN-09, GEN-10) | 6 / 6 | 6 / 6 | 6 / 6 |
| Source relationships handled (revised rules) | 0.867 | 1.000 | 1.000 |
| Conflict listed while the status says `answered` | 0 / 30 | 2 / 30 | 0 / 30 |
| Citation IDs valid; quotes found | 48/48; 48/48 | 52/52; 52/52 | 59/59; 59/59 |
| Statements the support heuristic confirmed | 46 / 48 | 52 / 52 | 56 / 59 |
| Same pass/fail in all 3 runs; same status in all 3 runs | 0.80; 1.00 | 1.00; 0.70 | 1.00; 0.90 |
| Mean answer length | 20.8 words | 22.1 (+6.2%) | 24.0 (+15.0%) |
| Mean input / output tokens per request | 2,144 / 255 | 2,264 / 292 | 2,388 / 306 |
| Mean / maximum latency | 3.48 / 5.59 s | 3.14 / 4.63 s | 3.10 / 4.79 s |
| Recorded cost; at list price without caching | $0.005277; $0.010260 | $0.005882; $0.011168 | $0.006151; $0.011750 |

- **Pass/fail:** no case changed between `robert_v3` and `josue_v3`. `compare_runs` reports no
  improvements and no regressions.
- **The 3 statements the heuristic didn't confirm** (`josue_v3`): two are explicit inferences
  ("The documents give conflicting operating results"), and one is an artifact where "FY2026" was
  read as the number "026". None is unsupported content.
- **Significance:** the differences are not significant. On the dated cases' status, 6/6 against
  3/6 gives Fisher p = 0.18. On the statements the heuristic confirmed, 56/59 against 52/52 gives
  p = 0.25. The repeated runs are not independent.
- **Criteria:** the five criteria fixed on 2026-11-15 were for `robert_v3` against v2. Applied
  afterwards to `josue_v3`, it meets four. It misses the length criterion (under 10% longer than
  v2): its answers are 15.0% longer.

## The 40-case benchmark: PR #1's own run, re-scored

PR #1's `josue_v3` benchmark run (`evaluation/results/20261121T200504Z_…_v3_live-v3-x3.json` at
`b0dc869`) was re-scored with the same audit, in `audit/benchmark/`. The audit reproduced its
stored scores exactly. The benchmark cases, documents and scorer are identical on both branches.

| Measure | `robert_v3` (2026-11-15) | `josue_v3` (PR #1, 2026-11-21) |
|---|---|---|
| Case runs passed, original / revised scoring | 119 / 120 of 120 | 120 / 120 of 120 |
| CF-01 conflict label (unresolved discrepancy) | context difference 3 of 3 | unclear 1, direct contradiction 1, context difference 1 |
| CF-02 (dated spending) and CF-03 (superseded) handled | 3/3 and 3/3 | 3/3 and 3/3 |
| Conflict listed while the status says `answered` | 4 of 102 QA case runs | 0 of 102 |

**Caveat.** PR #1's run was made from an uncommitted working tree on top of `6a93cee`, with
Python 3.13.9 and openai 3.57.0. The run files record no prompt hash, so it cannot be verified
that the run used exactly the `b0dc869` file. Its v3 was also written and measured on the same 40
cases.

## Files

| Path | Contents |
|---|---|
| `prompts/robert_v3/`, `prompts/josue_v3/` | Byte-identical copies of the two evaluated files |
| `run_josue_v3.py` | Harness that ran `josue_v3` (free estimate without `--allow-paid`) |
| `results/` | The `josue_v3` run (JSON and Markdown, as written by the runner) and its provenance |
| `audit/` | Revised-rule audit of v2, `robert_v3` and `josue_v3` on the generalization set |
| `audit/benchmark/` | Re-score of PR #1's `josue_v3` benchmark run and `robert_v3`'s benchmark run |
| `manifest.json` | Commits, blobs and SHA-256 hashes of every prompt and run compared |

## How to reproduce

The paid step needs an authorized budget.

```bash
python -m evaluation.experiments.v3_comparison.run_josue_v3
```

```bash
python -m evaluation.experiments.v3_comparison.run_josue_v3 --allow-paid --max-cost-usd 0.10
```

```bash
python -m evaluation.scoring_audit --dataset generalization --out evaluation/experiments/v3_comparison/audit evaluation/results/generalization/20261115T060208Z_openai_gpt-6-luna_v2_gen-v2-x3.json evaluation/results/generalization/20261115T060343Z_openai_gpt-6-luna_v3_gen-v3-x3.json evaluation/experiments/v3_comparison/results/20261124T013730Z_openai_gpt-6-luna_josue_v3_gen-josue-v3-x3.json
```
