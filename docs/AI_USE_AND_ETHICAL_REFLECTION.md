# AI Use and Ethical Reflection

AAI-530 places this project at **Level 4 of the AI Assessment Scale (AIAS)**: AI assistance is
intentional, extensive and documented. This document records which AI tools did what, how their work
was checked, and the ethical risks of the application itself.

Statements marked **[TEAM TO CONFIRM]** describe human activity that the AI assistant cannot attest
to. The team should edit them to match what actually happened before submission.

## 1. AI tools used and their roles

| Tool | Role in this project | Evidence |
|---|---|---|
| **ChatGPT** (OpenAI) | Planning, architectural specification, prompt development, technical review and quality assurance. The master development brief given to Claude Code was prepared with ChatGPT. **[TEAM TO CONFIRM: list the specific ChatGPT sessions/outputs used and what was adopted.]** | The brief itself |
| **Claude Code** (Anthropic; model Claude Opus 5.5) | Implementation: researched provider documentation, selected the architecture, wrote all application code, prompts, synthetic fixtures, labelled test cases, automated tests, evaluation tooling and documentation; ran the tests, benchmarks and offline evaluation; reviewed the UI in a browser and captured the screenshots | This repository; the development session (2026-11-13) |
| Web fetch of official provider pages (by Claude Code) | Verified model lists, prices, structured-output features, rate limits and data policies | URLs cited in `docs/API_SELECTION_REPORT.md` |
| Browser automation (built-in browser pane, Playwright) | Visual review of the running app; authentic screenshots in `assets/screenshots/` | Screenshots |

No other AI tools were used by Claude Code. **[TEAM TO CONFIRM: add any other tools the team used,
e.g. for slides or proofreading.]**

## 2. How AI-generated work was checked

Claude Code operated under explicit rules: never fabricate results, citations, screenshots or test
outcomes; distinguish implemented from verified; do not spend money or push to GitHub without
authorization. The checks that were actually performed:

| Check | What it caught |
|---|---|
| 307 automated tests, all executed (`python -m pytest`) | Logic errors in extraction, chunking, retrieval, prompts, citation checks, providers and UI flows |
| Dataset integrity tests: every reference fact must appear on its expected page of the real PDFs | Protects against AI-drafted reference answers that the documents do not support; caught a hyphenation bug |
| Provider contract tests against the real SDKs with mocked HTTP | Caught an adapter importing a library the current SDK no longer uses (`httpx` vs `httpx2`) |
| Retrieval benchmark and offline end-to-end evaluation | Measured retrieval choices; revealed a ranking regression from boilerplate removal |
| Visual review of the running app in a browser | Caught partial highlights (PDF ligatures), LaTeX rendering of dollar amounts, layout overflow |
| Lint/format (Ruff) and a Python 3.10-grammar syntax check | Code quality; a syntax construct that would fail on Python 3.11 |
| Re-reading official provider pages, with a second verification pass for figures first seen in summarized page text | Corrected an initial "not found" for two Gemini prices |
| Staged live evaluation of `gpt-6-luna` under an authorized budget (203 case runs, $0.056 computed from token counts) | One genuine failure: an earlier dated figure left out (CF-02). Also showed where automatic scores disagree with the cases' criteria |
| Prompt v3 test and a separate 10-case generalization set, with cases and pass criteria written before any model run (another $0.043 under separate authorizations) | Confirmed the targeted fix for dated figures on new documents (v3: 30 of 30 case runs; v2: 26 of 30) without regressions. These are automatic scores, not human verification |
| Scoring audit: original scores reproduced exactly from the saved answers; revised rules tested on made-up examples written separately from the fixtures | Two automatic rules stricter than the cases' own criteria (conflict handling; injection answers that quote the planted text in order to flag it) |

The full list of defects found and fixed is in `docs/PROMPT_AND_TESTING_APPENDIX.md`, Section I.

**Human review.** **[TEAM TO CONFIRM]** Before submission each team member should record what they
personally reviewed, for example: Robert reviewed the architecture and ran the app; Josue reviewed the
prompts and ran the prompt comparison; Marie reviewed the test cases (setting
`reference_verified_by_human` to true) and the ethics analysis. Do not record reviews that did not
happen.

## 3. Limits of AI assistance in this project

* **Circular validation.** The same assistant wrote the system and the test cases. The cases were
  aimed at known weaknesses and the baseline fails 17 of 40, but the team should add independent
  cases before drawing conclusions. The assistant also wrote the scoring audit's revised rules after
  it had read the live answers. They are proposals for the team to review, and every outcome they
  change is listed.
* **Possible vendor bias.** The provider comparison was drafted by an Anthropic model. It relies only
  on cited official figures, discloses the conflict, and leaves the final choice to a measured
  benchmark; the provisional choice is an OpenAI model.
* **Partly verified live behavior.** One model (`gpt-6-luna`) was measured on 40 synthetic cases,
  with automatic scoring only. Its behaviour on real documents, other models' behaviour, and any
  human judgement of the answers are still unverified.
* **Knowledge currency.** Model names and prices change quickly; they were read from official pages on
  2026-11-13 and must be re-checked.

## 4. Ethical risks of the application and how they are handled

| Risk | Mitigations implemented | Remaining risk |
|---|---|---|
| **Hallucinated answers** | Retrieval-grounded prompts; abstention status; schema-constrained output; numbers in answers that appear in no source are flagged; offline mode labelled as non-AI | Models can still misread or over-generalize from real passages |
| **Unsupported or fabricated citations** | IDs are generated by the app and validated; verbatim quotes are checked against the cited passage; a heuristic support score; the UI never says "verified", only what was checked | A real quote can still be used to support a wrong claim (offline example MI-01); the support check is lexical, not semantic |
| **Privacy and confidential documents** | Processing in memory only; nothing written to disk; no cross-session caches; logs contain no document text, questions or keys; clear-session control; uploads capped in size and number | Hosted models receive the question and passages; users may upload documents they are not allowed to share |
| **API data transmission** | Sidebar disclosure naming the provider; OpenAI requests sent with `store=false`; the report documents each provider's retention and training policy; free Gemini tier flagged as unsuitable for confidential data | Provider-side retention (e.g. 30-day abuse monitoring) is outside the app's control |
| **Prompt injection** | Instruction hierarchy; documents marked untrusted; delimiter neutralization; heuristic flagging shown to both the model and the user; fabricated-ID and canary detection; adversarial test fixture | Heuristics miss novel phrasings; no defence is complete; the offline baseline itself quoted an injected instruction (INJ-02) |
| **Bias** | Answers restricted to the documents; synthetic, neutral fixtures | The model can reflect biases in documents or its training when summarizing; tokenization and stemming are English-centric; non-English documents are untested |
| **Accessibility** | Text labels on every status color; alt text on page images; keyboard-operable native Streamlit widgets; high-contrast palette; plain-language messages | No formal WCAG audit or screen-reader testing has been done |
| **Transparency** | Every answer shows its sources, quote checks and diagnostics (model, prompt version, retrieval, tokens, cost); offline mode is labelled; About tab explains the method and limits | Users may still over-trust a fluent answer |
| **Copyright** | Only synthetic sample documents are distributed; uploads are never stored or redistributed; quotes are short | Users are responsible for their right to process uploaded documents |
| **Misuse** | Scope limited to analyzing uploaded documents; prompt instructs declining off-task requests; request budget per session | Could be used to extract personal data from documents a user should not have; no authentication in this prototype |
| **Consequential decisions** | Persistent disclaimer; prompt forbids legal/medical/financial conclusions beyond the documents; inference vs fact labelling; conflicts shown instead of resolved | Final responsibility rests with the human reviewer |

## 5. Human oversight

DocIntel is designed as a reading aid, not a decision-maker: it shows where an answer comes from so a
person can check it quickly. The intended workflow is ask, inspect the highlighted evidence, open the
cited page, then decide. The evaluation framework likewise reserves usefulness and faithfulness
judgements for human reviewers.

## 6. Reflection

**[TEAM TO COMPLETE]** Suggested prompts for a short team reflection (a paragraph each):

1. Where did AI assistance save the most time, and where did it need the most correction?
2. Which AI-generated artifact did you trust least, and how did you check it?
3. What did the offline baseline's failures (near-miss answers with valid citations, quoting an
   injected instruction) teach you about "grounded" systems?
4. Would you deploy this for real documents? What would have to change first?
