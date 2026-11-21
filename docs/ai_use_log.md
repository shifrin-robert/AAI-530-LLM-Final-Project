# AI Use Log

Append-only. One entry per work session, newest at the bottom. Record what the AI tool did, what you
checked or changed, and what you rejected. This log feeds `docs/AI_USE_AND_ETHICAL_REFLECTION.md`.

### 2026-11-21 – Josue – Windows test failure (task J0)
- Tool: Claude Code
- Used for: diagnosing `test_paraphrase_cases_point_to_pages_containing_the_source_wording`, which
  failed on Windows only; finding other places with the same problem.
- Cause: the tests read JSON and config files with `read_text()` and no encoding, so Windows used
  cp1252 and read `°C` as `Â°C`. The PDF fixture itself was correct (checked the code points).
- What changed: added `encoding="utf-8"` to the file reads in `tests/test_evaluation_dataset.py` and
  `tests/test_security.py`; `scripts/verify_project.py` now compares paths with forward slashes
  (`as_posix()`), because on Windows it wrongly flagged the synthetic fixture PDFs.
- What I checked: `python -m pytest` (186 passed, 4 skipped for optional SDKs) and
  `python scripts/verify_project.py` (6/6) on Windows.
- Rejected: nothing.

### 2026-11-21 – Josue – live API smoke test
- Tool: Claude Code
- Used for: moving my OpenAI key out of the tracked `.env.example` into the git-ignored `.env`
  (without displaying it), then running the 3-case smoke test from `docs/LIVE_EVALUATION_GUIDE.md` Step 7a.
- Result: gpt-6-luna, prompt v2, cases DF-01, MI-04, INJ-02: 3/3 pass, 0 errors, $0.000675 recorded cost
  (estimate was $0.004). Output in the git-ignored `evaluation/results/scratch/` folder, as the guide says.
- What I checked: spend limit set and auto-recharge off before running; `.env` ignored by git.
- Rejected: nothing.

### 2026-11-21 – Josue – live prompt v1 vs v2 evaluation (task J1)
- Tool: Claude Code
- Used for: running the 40-case evaluation on gpt-6-luna with prompt v2 (`live-v2`) and v1 (`live-v1`),
  same model, cases and retriever, then `evaluation.compare_runs`.
- Result: v2 40/40, v1 37/40. v2 fixed CF-01, CF-02 (conflicting evidence) and INJ-03 (prompt
  injection); no case got worse. Recorded cost $0.0128 (v2) + $0.0134 (v1).
- What I checked: read the failure reasons and the scoring code. v2's conflict_handling_rate is 0.667
  because on CF-03 it explained both uptime values (99.5% before the amendment, 99.9% after) in the
  answer text but did not fill the structured conflicts field; the answer itself is correct.
- Rejected: nothing.

### 2026-11-21 – Josue – prompt and testing appendix (task J2)
- Tool: Claude Code
- Used for: writing the measured v1 vs v2 results into `docs/PROMPT_AND_TESTING_APPENDIX.md`
  (Section E effect table, Section H.2 live outputs, Section I row 12, Section J.1 metrics).
- What I checked: every quoted model answer was compared by script with the run JSON files (0
  mismatches); metrics copied from the `compare_runs` output.
- Judgment call: recorded that v1's INJ-03 failure is a strict-scoring artifact (it quoted the
  planted phrase while flagging it), instead of claiming v2 fixed a real injection failure.

### 2026-11-21 – Josue – consistency run (prompt v2 x 3)
- Tool: Claude Code
- Used for: running the 40 cases three times with prompt v2 on gpt-6-luna (`live-v2-x3`) and reading
  the per-repeat answers of the failing cases.
- Result: 116/120 pass; outcome and status agreement across repeats 0.95; recorded cost $0.0283.
  All 4 failures are CF-01 and CF-02 (conflicting evidence). 38 of 40 cases gave the same result
  every time.
- What I checked: the failing answers. CF-02 twice reported only the latest spending figure; CF-01
  once gave only one date, and once gave both dates but used status `answered`. Retrieval is
  deterministic, so the variation comes from the model, not the search.
- Conclusion: v2's conflict handling is better than v1 but not reliable; a v3 conflict rule is worth
  considering.

### 2026-11-21 – Josue – prompt v3 (stricter conflict rule)
- Tool: Claude Code
- Used for: writing `prompts/grounded_qa_v3.md` after the consistency run showed v2 handled CF-01 and
  CF-02 correctly only 2 times out of 4. v3 is v2 with only section 7 rewritten: check all sources
  for differing values, never drop a version, keep `status` and `conflicts[]` consistent, keep the
  amendment exception (MD-01/MD-02) and do not invent conflicts when sources agree (MD-03).
- Registered v3 in `prompting.py`, `config.py`, the app's prompt selector, the evaluation runner,
  `.env.example` and the audit script; v2 stays the default until v3 is measured.
- What I checked: new test that v3 differs from v2 only in section 7; full suite 189 passed, audit
  6/6; a free offline run with `--prompt-version v3` works.
- Rejected: adding a rule to avoid repeating planted phrases (INJ-03), because it would tune the
  prompt to a scoring artifact rather than a real failure, and would mix two changes in one test.

### 2026-11-21 – Josue – prompt v3 consistency run (v3 x 3)
- Tool: Claude Code
- Used for: running the 40 cases three times with prompt v3 (`live-v3-x3`) and comparing with the v2
  x 3 run using `evaluation.compare_runs`.
- Result: v3 120/120 (v2 116/120); outcome agreement 1.0 (v2 0.95). CF-01 and CF-02 now report both
  versions with status `conflicting_evidence` in all 3 repeats. MD-01..03 still pass (amendment
  exception works; no invented conflict when sources agree). Recorded cost $0.0327 (v2 x 3: $0.0283).
- What I checked: the small drop in quote_match_rate (0.993) comes from SUM-01 and EXT-01, whose
  prompts v3 does not change, so it is model variation, not a v3 effect. Status varied only on MI-01
  (partially_answered vs insufficient_evidence, both accepted).

### 2026-11-21 – Josue – v3 made the default; appendix updated with v3 results
- Tool: Claude Code
- Used for: switching the default QA prompt to v3 (`config.py`, evaluation runner default,
  `.env.example`, the app's prompt selector, my local `.env`), pointing the prompt-rendering tests at
  v3, and updating the docs that named v2 as the default (README, project documentation, user guide,
  requirements traceability).
- Appendix: v3 in the prompt inventory, full new section 7 (C.3), v3 row and consistency findings in
  Section E, v2 x 3 vs v3 x 3 outputs (H.3) and metrics (J.2).
- What I checked: every quoted output compared by script with the run JSON (0 mismatches); corrected
  my own draft claim about the unmatched quotes to the measured 3 of 437; full test suite and audit.
- Not changed: `prompts/grounded_qa_v2.md` (old prompt files are never edited, so its header still
  says `default`); `docs/EVALUATION_REPORT.md` (Angelique's) and the presentation script (later task).
