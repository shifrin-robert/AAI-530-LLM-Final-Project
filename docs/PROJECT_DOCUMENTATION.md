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
offline extractive provider are also implemented. The project includes 181 passing automated tests,
40 labelled evaluation cases over synthetic documents, a retrieval benchmark and an offline baseline
evaluation. **Live LLM evaluation has not been run** because no API key or spending approval was
available during development; the framework, commands and cost guards for it are in place.

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
Without a key the UI falls back to the offline extractive provider and says so.

## 10. Prompt customization

Eight versioned prompt files (`prompts/`). The default QA prompt (v2) defines the role, instruction
hierarchy, documents as untrusted evidence, grounding, citation and quote rules, insufficient-evidence
handling, conflicting-evidence handling (contradiction vs context difference), ambiguity, confidence,
output format and safety/confidentiality. v1 is a minimal baseline kept for the iteration experiment.
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

Five layers: automated tests; dataset integrity checks; retrieval benchmark; end-to-end evaluation
(offline baseline now, live models when authorized); human review. Automatic scoring checks required
facts, acceptable status, forbidden phrases, fabricated IDs, canary leaks, evidence pages, extraction
recall and comparison constraints. Full method: `docs/EVALUATION_REPORT.md`.

## 16. Test cases

40 labelled cases over synthetic fixtures: direct factual (8), multi-page (4), multi-document (4),
numerical (4), missing information (5), conflicting evidence (3), prompt injection (4), ambiguous (2),
summarization (2), extraction (2), comparison (2); plus 12 paraphrase retrieval cases. Reference facts
are machine-checked against the fixture pages. Table: `docs/PROMPT_AND_TESTING_APPENDIX.md` §G.

## 17. Actual results

* **Automated tests:** `python -m pytest` -> 181 passed.
* **Retrieval (collection setting):** on paraphrased questions BM25 got the right page into the model's
  context for 9 of 12 questions; hybrid and character n-grams for 11 of 12. On exact-wording questions
  all methods reached 100%; BM25 ranked slightly better (MRR 0.933 vs 0.917 for hybrid).
* **Offline extractive baseline (not an LLM):** 23/40 cases passed; answer accuracy 0.615, correct
  abstention 0.600, conflict handling 0.000, injection resistance 0.750, citation ID validity 1.000,
  extraction recall 0.900.
* **Live LLM results:** none yet.

## 18. Prompt revisions

v1 -> v2 added the instruction hierarchy, untrusted-document rules, verbatim quotes, fact/inference
labels, partial and insufficient statuses, the conflict procedure, ambiguity and confidence rules and
confidentiality. The revisions came from reviewing v1 against the test categories and the validator's
needs, not from live failures; the measured comparison is pending.

## 19. Failure analysis

Offline baseline failures show the risks the LLM prompts address: a near-miss question answered with
a valid but irrelevant citation (MI-01), an injected instruction quoted as an answer (INJ-02),
conflicts reduced to one side (CF-01), multi-page questions missed. Development failures and fixes
(hyphenation corrupting compound words, boilerplate in every chunk, a ranking regression after its
removal, an SDK dependency change, PDF ligatures breaking highlights) are documented with their
verification in the appendix, Section I.

## 20. Security

Secrets only via environment variables (`.env` git-ignored, `.env.example` empty); keys read on demand
as `SecretStr` and never logged; uploads validated and capped; in-memory processing without temporary
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

* No live LLM evaluation yet; LLM behavior is designed but unmeasured.
* Lexical retrieval misses pure synonyms (measured: "drinks" vs "alcoholic beverages").
* No OCR; complex tables and multi-column layouts may extract imperfectly.
* Chunks do not cross pages, so a sentence split by a page break is split between chunks.
* The citation support check is lexical; the injection filter is heuristic.
* Comparison of very large documents uses a subset of passages (reported in the coverage note).
* Small synthetic evaluation set written by the same assistant that built the system.
* Single-server session isolation only; no authentication, persistence or audit trail.
* English-centric tokenization; tested on Python 3.14.4 only (syntax checked against 3.10 grammar).

## 26. Future improvements

1. Run the live benchmark and prompt v1/v2 comparison; complete human review.
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
remaining step is empirical: run the prepared live evaluation, compare prompts and models, and let the
measurements decide the final configuration.
