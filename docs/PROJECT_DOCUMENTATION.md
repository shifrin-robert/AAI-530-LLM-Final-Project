# DocIntel AI: Project Documentation

AAI-530 Large Language Model Engineering, final project. Team: Robert, Josue, Marie.
Version 1.0.0, 2026-11-13.

## 1. Executive summary

DocIntel AI is a Streamlit application that lets a user upload PDFs and ask questions, generate
summaries, extract structured information and compare documents, with every answer tied to
verifiable passages and pages. It is a retrieval-augmented generation (RAG) system built without
heavy frameworks: PyMuPDF extracts text in memory, a deterministic hybrid retriever (BM25 + character
n-grams) selects passages, versioned prompts present them to an LLM as untrusted, labelled sources,
the LLM must return schema-valid JSON with verbatim quotes, and the application independently checks
every citation before showing highlighted evidence.

The provisional model is OpenAI `gpt-6-luna` (about $0.15 per 100 typical requests), chosen after a
documented comparison of OpenAI, Anthropic and Google models; Anthropic and Gemini adapters and an
offline extractive provider are also implemented.

The project includes 307 passing automated tests, 40 labelled benchmark cases over synthetic
documents, a separate 10-case generalization set, a retrieval benchmark, an offline baseline and a
live evaluation of `gpt-6-luna` that cost $0.099 in total (2026-11-14 and 2026-11-15).

* **Prompt v2:** passed 39 of 40 benchmark cases, and 155 of 160 over four runs.
* **Prompt v3** (v2 plus one rule for figures reported as of different dates): passed 119 of 120
  over three runs, against 116 for v2's three runs. On the generalization set it passed 30 of 30,
  against 26 of 30 for v2. It fixed every dated-spending case, with no case-level regression.
* **Adoption:** v3 became the default on 2026-11-15. v1 and v2 remain available.

These scores are automatic, on synthetic documents and small samples. They are not statistically
significant per case, and no result has been reviewed by a person yet.

## 2. Real-world problem

Contracts, reports, policies and research papers are long, and the facts people need are scattered
across pages and documents. General chatbots answer fluently but do not show where answers come
from, may invent figures, cannot tell an amended contract term from a contradiction, and can be
manipulated by text hidden in a document. People who must rely on the answer need to see and check
the evidence quickly.

## 3. Intended users

Students and researchers reading papers and reports; business professionals and analysts reviewing
contracts, amendments, status reports and memos; anyone who needs to understand a long or complex
document and verify the parts they will act on. The prototype assumes English-language, text-based
PDFs.

## 4. Project goals

1. Answer questions from uploaded documents only, with page-level citations a user can check.
2. Say "not in the documents" instead of guessing; show disagreements instead of resolving them.
3. Summarize, extract and compare documents with the same grounding discipline.
4. Resist instructions embedded in documents.
5. Measure behavior with labelled cases and report results honestly.
6. Keep the system simple, reproducible, cheap and private enough for an academic prototype.

## 5. Requirements

The six AAI-530 requirements and five deliverables are mapped to files, tests and statuses in
`docs/REQUIREMENTS_TRACEABILITY.md`. In short: applied use case (1), LLM integration (2), prompt
customization (3), context/evaluation/safety features (4), testing and evaluation (5), documentation
and ethics (6).

## 6. Architecture

```text
PDF -> validate -> extract pages -> remove boilerplate -> page-aware chunks -> hybrid index
question -> retrieve -> context budget -> versioned prompt (sources as data) -> LLM (JSON schema)
        -> citation checks -> answer + highlighted evidence
```

One process, no database or vector store; one in-memory `DocumentWorkspace` per browser session.
Details, module responsibilities and design decisions: `docs/ARCHITECTURE.md`.

## 7. Technology stack

Python 3.11+ (developed and tested on 3.14.4); Streamlit 1.67 (UI); PyMuPDF 2.1 (PDF parsing and page
rendering); Pydantic 2 (schemas and validation); python-dotenv (configuration); OpenAI SDK 3.51,
Anthropic SDK 2.8 and google-genai 3.3 (providers); pytest and Ruff (testing, linting). Exact versions:
`requirements-lock.txt`.

## 8. API selection

Eleven current models from OpenAI, Anthropic and Google were compared on structured-output support,
context window, price, data handling, rate limits and SDK support, using official documentation read
on 2026-11-13 (`docs/API_SELECTION_REPORT.md`). OpenAI `gpt-6-luna` and Anthropic `claude-haiku-5-5`
tie as the cheapest (USD 0.10 input / 0.50 output per million tokens); `gpt-6-luna` was chosen
provisionally for strict JSON-schema decoding, `store=false` control, rate limits and the team's
preference. The choice must be confirmed by the live benchmark.

## 9. Model integration

`LLMProvider.generate()` wraps every provider with the same behavior: per-session request budget
(default 200 calls), bounded retries (default 2) with exponential backoff capped at 20 s and
`Retry-After` support, one retry for schema-invalid output, timeouts (default 60 s), token, latency
and cost accounting, and user-safe error messages. The OpenAI adapter calls
`client.responses.parse(model, instructions, input, text_format=Schema, max_output_tokens, store=False,
reasoning={"effort": "low"})`. Model identifiers appear only in `model_catalog.py` and configuration.
Each user brings their own API key, entered in the sidebar and kept only in that browser session;
server keys are used only in explicit owner mode (`DOCINTEL_KEY_MODE=owner`). Without a key the UI
falls back to the offline extractive provider and says so.

## 10. Prompt customization

Nine versioned prompt files (`prompts/`). The default QA prompt (v3) defines the role, instruction
hierarchy, documents as untrusted evidence, grounding, citation and quote rules, insufficient-evidence
handling, conflicting-evidence handling (contradiction vs context difference), ambiguity, confidence,
output format and safety/confidentiality. v3 is v2 plus one rule: figures reported as of different
dates are all given, each with its date. v2 (the previous default) and v1 (a minimal baseline) are
kept for comparison.
Version history, reasons and full text: `docs/PROMPT_AND_TESTING_APPENDIX.md`.

## 11. PDF processing

Validation before parsing (size, extension, `%PDF-` header) and after opening (corrupt, encrypted with
a user password, zero pages, page limit). Text is extracted block by block in reading order, normalized
(Unicode NFKC including ligatures, non-breaking and zero-width spaces, soft hyphens, line-end
hyphenation repaired only when the joined word occurs elsewhere in the document). Running headers and
footers repeated on at least 60% of pages are removed and reported. Pages without text are kept and
listed; documents with no text at all are rejected with an OCR explanation. Everything happens in
memory; nothing is written to disk.

## 12. Retrieval and context handling

Chunks of up to 1,000 characters with 150 characters of sentence-aligned overlap, never crossing a page
boundary, stored with exact character offsets. Each chunk is indexed with its document title.
Retrieval is a reciprocal-rank fusion of BM25 (light stemming, number normalization, stop words) and
character 4-gram TF-IDF. Context selection takes the top passages up to 8 passages or ~6,000 estimated
tokens, skips overlapping duplicates and caps passages per document when several are in scope.
Retrieval was benchmarked on 26 standard and 12 paraphrased questions (Section 17).

## 13. Source citations

The application assigns request-scoped IDs (S1, S2, ...). The model may only cite those IDs and must
give a verbatim quote for each citation. `grounding.py` reports, separately: whether each ID was
provided; whether the quote is in the cited passage (exact, approximate or not found); a heuristic
support score (content words and numbers of the claim found in the cited passages); numbers in the
answer found in no source; and prompt-canary leakage. The overall verdict (`grounded`, `review`,
`unsupported`, `abstained`) is shown with an explanation that passing checks does not prove
correctness. The UI shows each cited passage with the quoted words highlighted and can render the
original PDF page with the quote highlighted.

## 14. Application workflows

* **Ask:** chat with follow-ups (previous question used for retrieval; previous answers labelled
  unverified), document scope filter, status badges, conflicts, missing information, inferences,
  confidence, ratings, evidence panel and diagnostics.
* **Summarize:** single pass for short selections; map-reduce for long ones (up to 12 sections per
  run), with a pre-flight call/cost estimate and an explicit coverage report.
* **Extract:** nine categories, section by section, merged and de-duplicated in code; values with
  details or "not stated", normalized forms, sources and quote checks; JSON download.
* **Compare:** two to four documents with an even context split; findings grouped by type with
  contradiction/context labels; cross-document findings must cite both documents.

## 15. Evaluation methodology

Six layers:

1. automated tests;
2. dataset integrity checks;
3. retrieval benchmark;
4. end-to-end evaluation: the offline baseline, then GPT-6 Luna with prompts v1 and v2
   (2026-11-14), then v3 (2026-11-15);
5. a scoring audit of the automatic rules;
6. human review (the worksheet is ready, but no case has been reviewed).

A separate generalization set of 10 new cases tests whether v3's rule carries over to new
documents. It was run for v2 and v3 on 2026-11-15.
 Automatic scoring checks required
facts, acceptable status, forbidden phrases, fabricated IDs, canary leaks, evidence pages, extraction
recall and comparison constraints. Full method: `docs/EVALUATION_REPORT.md`.

## 16. Test cases

40 labelled cases over synthetic fixtures: direct factual (8), multi-page (4), multi-document (4),
numerical (4), missing information (5), conflicting evidence (3), prompt injection (4), ambiguous (2),
summarization (2), extraction (2), comparison (2); plus 12 paraphrase retrieval cases. Reference facts
are machine-checked against the fixture pages. Table: `docs/PROMPT_AND_TESTING_APPENDIX.md` §G.

## 17. Actual results

* **Automated tests:** `python -m pytest` -> 307 passed.
* **Retrieval (collection setting):** on paraphrased questions BM25 got the right page into the model's
  context for 9 of 12 questions; hybrid and character n-grams for 11 of 12. On exact-wording questions
  all methods reached 100%; BM25 ranked slightly better (MRR 0.933 vs 0.917 for hybrid).
* **Offline extractive baseline (not an LLM):** 23/40 cases passed; answer accuracy 0.615, correct
  abstention 0.600, conflict handling 0.000, injection resistance 0.750, citation ID validity 1.000,
  extraction recall 0.900.
* **Live LLM results:** GPT-6 Luna, automatic scoring, not human-reviewed.
  * Prompt v2 passed 39 of 40 cases.
  * Its other metrics: answer accuracy 0.962, correct abstention 1.000, false abstention 0.000,
    citation ID validity 1.000, quote match 1.000, heuristic support 0.964 (word overlap) and
    extraction recall 1.000.
  * Prompt v1 passed 37 of 40.
  * Three more v2 runs passed 116 of 120, with outcome agreement 0.95.
  * The total cost was $0.056, computed from the API's token counts.
* **Scoring audit:** two automatic rules were stricter than the cases' own criteria: the conflict
  rule, and the injection rule when an answer quotes injected text. Under the proposed revisions,
  v1 scores 38 of 40 and the v2 repeats 118 of 120; the v2 main run is unchanged at 39 of 40. The
  original scores remain the scores of record.
* **Genuine failure:** CF-02. The model gives only the later of two dated spending figures, although
  both were in its context. It passed 1 of 4 attempts with v2.
* **Prompt v3** (2026-11-15; automatic scoring), compared with v2's three runs:
  * passed 119 of 120 case runs (116 for v2), and 120 under the revised rules (118 for v2);
  * passed CF-02 in 3 of 3 runs, with no case worse;
  * +120 input tokens per question, the same list-price cost and the same latency.
  It met all four criteria fixed before the run. The difference is not statistically significant
  (Fisher p = 0.40 for CF-02).
* **Generalization set** (10 new cases, three runs per prompt, automatic scoring):
  * v2 passed 26 of 30 case runs and v3 passed 30 of 30;
  * on spending reported on two dates, v2 passed 2 of 6 and v3 6 of 6;
  * both prompts passed all 24 runs on current versus historical figures, revised budgets,
    compatible figures and genuine contradictions;
  * v3 met all five criteria fixed before the run, with no case-level regression;
  * Fisher p = 0.061 on the dated cases; the runs are repeated measurements of the same
    questions.

## 18. Prompt revisions

v1 -> v2 added the instruction hierarchy, untrusted-document rules, verbatim quotes, fact/inference
labels, partial and insufficient statuses, the conflict procedure, ambiguity and confidence rules and
confidentiality. The revisions came from reviewing v1 against the test categories and the validator's
needs, not from live failures.

Measured on 2026-11-14, v2 passed 39 of 40 cases and v1 passed 37. One of the two differences (INJ-03)
is a scoring artifact, and the difference is not statistically significant (exact McNemar p = 0.5).
v3 adds one rule for figures reported as of different dates. It is the first revision driven by an
observed live failure (CF-02). Tested on 2026-11-15, it fixed CF-02 in all three runs without
regressions. It also labelled CF-01's disagreement as a context difference, a classification the
report judges defensible but not the best fit.

The generalization set then showed the same fix on new documents (6 of 6 dated runs against 2 of 6)
without regressions. The team made v3 the default on 2026-11-15. It asked that CF-01 be treated as
an unresolved discrepancy, and that the app present conflict labels as the model's classification
(`docs/EVALUATION_REPORT.md`, Sections 7.3 to 7.6).

## 19. Failure analysis

Offline baseline failures show the risks the LLM prompts address: a near-miss question answered with
a valid but irrelevant citation (MI-01), an injected instruction quoted as an answer (INJ-02),
conflicts reduced to one side (CF-01), multi-page questions missed. Development failures and fixes
(hyphenation corrupting compound words, boilerplate in every chunk, a ranking regression after its
removal, an SDK dependency change, PDF ligatures breaking highlights) are documented with their
verification in the appendix, Section I.

Live model failures: CF-02 leaves out an earlier dated figure that was in its context. INJ-03
answers that flag the injected text by quoting it were failed by a phrase check that cannot tell
quoting from obeying. Details and the scoring audit are in `docs/EVALUATION_REPORT.md`, Sections 6
and 7.

## 20. Security

Bring your own key: each user's key stays in their own session, is used only for its provider and
is never shown, logged or written anywhere. Server keys (`.env` git-ignored, `.env.example` empty)
are used only in explicit owner mode. Session keys get SDK clients sealed against server
environment settings (see `docs/BYOK_SECURITY_REVIEW.md`). Keys are held as `SecretStr` and never
logged; uploads validated and capped; in-memory processing without temporary
files; session isolation without shared caches; safe error messages and hidden tracebacks
(`showErrorDetails = "none"`); logs limited to events, IDs, counts and timings; prompt-injection
defences (hierarchy, delimiters, flags, ID validation, canary); bounded retries and request budgets;
`store=false` for OpenAI; telemetry disabled. `scripts/verify_project.py` scans for secrets and files
that must not be committed.

## 21. Privacy

The app keeps documents only for the browser session. With a hosted model, the question and selected
passages (or whole documents for summaries/extraction) go to that provider; the sidebar says which
one. Provider policies (training, retention, zero-retention options) are compared in the API report.
Only synthetic documents are included in the repository. No claim of regulatory compliance (GDPR,
HIPAA, FERPA) is made.

## 22. Ethical considerations

Hallucination, unsupported citations, privacy, bias, transparency, copyright, misuse, prompt
injection and consequential decisions are analyzed with mitigations and remaining risks in
`docs/AI_USE_AND_ETHICAL_REFLECTION.md`. The central principle: the system supports human review and
never presents its own checks as proof.

## 23. Accessibility

Statuses use text labels, not color alone; page images carry alt text; native Streamlit widgets are
keyboard-operable; the palette has high contrast; messages use plain language. No formal WCAG audit
or screen-reader test was performed.

## 24. AI-assisted development

ChatGPT supported planning, specification and review; Claude Code implemented and tested the system
and wrote the documentation. How the work was verified and what the team must still confirm:
`docs/AI_USE_AND_ETHICAL_REFLECTION.md`. Proposed responsibilities and a fill-in contribution record:
`docs/TEAM_CONTRIBUTIONS.md`.

## 25. Known limitations

* Live LLM behavior is measured for one model (`gpt-6-luna`) on 40 synthetic cases, with automatic
  scoring only; human review has not started.
* Lexical retrieval misses pure synonyms (measured: "drinks" vs "alcoholic beverages").
* No OCR; complex tables and multi-column layouts may extract imperfectly.
* Chunks do not cross pages, so a sentence split by a page break is split between chunks.
* The citation support check is lexical; the injection filter is heuristic.
* Comparison of very large documents uses a subset of passages (reported in the coverage note).
* Small synthetic evaluation set written by the same assistant that built the system.
* Single-server session isolation only; no authentication, persistence or audit trail.
* English-centric tokenization; tested on Python 3.14.4 only (syntax checked against 3.10 grammar).

## 26. Future improvements

1. Complete the human review, extend the generalization set with team-written cases and real
   documents, and benchmark other models with the same harness.
2. Add embedding retrieval (or hybrid lexical + embeddings) and compare with the existing benchmark.
3. Optional OCR (for example Tesseract) with confidence reporting.
4. Semantic citation checking with an entailment model or calibrated LLM judge.
5. Larger, independently written evaluation set with real (licensed) documents.
6. Prompt caching for repeated document context; streaming responses.
7. Authentication, per-user quotas and deployment hardening for multi-user use.

## 27. Conclusion

DocIntel AI demonstrates LLM engineering beyond a chat wrapper: a deterministic, measured retrieval
layer; prompts designed around an explicit trust boundary; schema-constrained outputs; and an
independent verification layer that turns citations into checkable evidence. Its offline evaluation
shows both why grounding matters and why valid citations alone do not guarantee correct answers. The
live evaluation of GPT-6 Luna supports the design. Prompt v2 passed 39 of 40 cases, and the targeted
revision v3, now the default, fixed v2's one remaining failure on the benchmark and on new documents
at about the same cost. All of these are automatic scores on synthetic documents. Three steps
remain before the results can be trusted beyond them:

1. human review;
2. team-written cases over real documents;
3. a comparison with other models.
