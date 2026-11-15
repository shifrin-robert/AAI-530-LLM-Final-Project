# Requirements Traceability

Status key:

| Status | Meaning |
|---|---|
| **COMPLETE** | Implemented and verified |
| **LIVE-TESTED** | Run against a real LLM API (OpenAI `gpt-6-luna`, 2026-11-14) and scored automatically. Not yet human-reviewed |
| **IMPLEMENTED, NOT LIVE-VERIFIED** | Implemented and tested offline only |
| **PARTIAL** | Some work remains |
| **BLOCKED** | Needs an external authorization or resource |

No requirement is marked as human-verified, because the human review has not started.

## AAI-530 requirements

| # | Requirement | Where it is met | Verification | Status |
|---|---|---|---|---|
| 1 | Applied LLM use case | Document analysis for students, researchers, analysts and professionals: grounded Q&A, summaries, extraction, comparison (README; `docs/PROJECT_DOCUMENTATION.md` §2-4) | App runs end to end (AppTest + browser review) | **COMPLETE** |
| 2 | LLM integration | `src/docintel/llm_client.py`: OpenAI Responses API (default `gpt-6-luna`), Anthropic Messages API, Gemini API; config-driven model selection; `docs/API_SELECTION_REPORT.md` | Contract tests against the real SDKs with mocked HTTP (`tests/test_llm_client.py`); live OpenAI runs: 203 case runs, 0 errors, schema-valid output in all (`docs/EVALUATION_REPORT.md` §5) | OpenAI **LIVE-TESTED**; Anthropic and Gemini **IMPLEMENTED, NOT LIVE-VERIFIED** |
| 3 | Prompt / instruction customization | Versioned prompts in `prompts/` (QA v1, v2 and proposed v3, summarization map/reduce, extraction, comparison, judge); strict JSON schemas (`models.py`); revision history (`docs/PROMPT_AND_TESTING_APPENDIX.md` §E) | Prompt tests (`tests/test_prompting.py`) incl. coverage of the 10 required instruction elements | Prompts **COMPLETE**; v1 vs v2 **LIVE-TESTED** (37/40 against 39/40; not statistically significant); v3 proposed, **not run** (needs approval to spend) |
| 4 | Context, evaluation or safety feature | RAG over uploaded PDFs; page-level source grounding; citation validation (IDs, verbatim quotes, support heuristic, numbers); unsupported-answer handling; conflict reporting; prompt-injection defences | `tests/test_grounding.py`, `tests/test_workflows.py`, `tests/test_security.py`; offline evaluation; live evaluation (no fabricated citation ID or prompt-canary leak in 203 live case runs; 5/5 correct abstentions per run) | **COMPLETE** (offline); **LIVE-TESTED** with `gpt-6-luna`. Citation support is checked only heuristically |
| 5 | Testing and evaluation | 285 automated tests; 40 labelled cases; retrieval benchmark; offline end-to-end baseline; live evaluation of `gpt-6-luna` (prompts v1 and v2, v2 three more times); scoring for accuracy, citation support, abstention, conflicts, injection, consistency, cost; scoring audit; human review worksheet | `docs/EVALUATION_REPORT.md`; run files in `evaluation/results/`; `evaluation/audit/`; `evaluation/human_review/` | Framework, offline and live results **COMPLETE** (automatic scoring); scoring audit **COMPLETE** (revised rules proposed, not adopted); human review **NOT STARTED** (worksheet ready); other models **BLOCKED** (need approval to spend) |
| 6 | Documentation, AI use, ethical reflection | `docs/` (project documentation, architecture, appendix, evaluation, AI use and ethics, user guide, presentation) | Reviewed against this table | **PARTIAL**: written; team confirmations marked [TEAM TO CONFIRM] remain |

## Deliverables

| # | Deliverable | Location | Status |
|---|---|---|---|
| 1 | GitHub repository | https://github.com/shifrin-robert/AAI-530-LLM-Final-Project (`main`). The later local work (bring your own key, live evaluation documentation) is not pushed yet; pushing needs the team's authorization | **PARTIAL** |
| 2 | Written project documentation | `docs/PROJECT_DOCUMENTATION.md`, `docs/ARCHITECTURE.md`, `docs/API_SELECTION_REPORT.md`, `docs/EVALUATION_REPORT.md`, `docs/USER_GUIDE.md` | **COMPLETE** (live results added; human review pending) |
| 3 | Prompt and testing appendix | `docs/PROMPT_AND_TESTING_APPENDIX.md` | **COMPLETE**, including the live v1-vs-v2 comparison and the scoring audit; other models and prompt v3 not run |
| 4 | AI use and ethical reflection | `docs/AI_USE_AND_ETHICAL_REFLECTION.md` | **PARTIAL** (team reflection and confirmations needed) |
| 5 | Presentation and demonstration | `docs/PRESENTATION_SCRIPT.md`, `docs/DEMO_WALKTHROUGH.md`, `assets/screenshots/` | Materials **COMPLETE**; recording **not created** (team task) |

## Functional requirements from the brief

| Area | Implementation | Tests | Status |
|---|---|---|---|
| Multiple PDF upload, validation, limits, corrupt/encrypted/empty/scanned handling | `pdf_processing.py`, `session.py`, sidebar | `test_pdf_processing.py`, `test_app.py::test_upload_valid_and_invalid_files` | COMPLETE |
| Page and metadata preservation; document removal; session clearing | `models.py`, `chunking.py`, `session.py` | `test_chunking.py`, `test_workflows.py` | COMPLETE |
| Deterministic chunking, configurable size/overlap | `chunking.py` | `test_chunking.py` | COMPLETE |
| Lexical baseline + evaluated alternative retrieval | `retrieval.py` (BM25, char n-gram, hybrid) | `test_retrieval.py`, `evaluation/retrieval_eval.py` | COMPLETE (embeddings: future work) |
| Context budget, multi-document retrieval, diagnostics | `retrieval.select_context`, `qa.py` | `test_retrieval.py` | COMPLETE |
| Grounded QA: abstention, conflicts, fact vs inference, follow-ups | `qa.py`, `grounded_qa_v2.md`, `QAOutput` | `test_workflows.py` (scripted outputs); live evaluation (34 QA cases) | LIVE-TESTED |
| Citation IDs generated by app, validated; quote checks; support evaluation separate from ID validity | `grounding.py` | `test_grounding.py` | COMPLETE |
| Evidence viewer with page rendering | `app.py`, `render_page_png` | Browser review, `test_render_page_png_with_highlight` | COMPLETE |
| Hierarchical summarization with coverage reporting | `summarization.py` | `test_workflows.py` (map-reduce, partial coverage); live evaluation (SUM-01, SUM-02) | LIVE-TESTED |
| Structured extraction with sources, nulls for missing details | `extraction.py`, `ExtractionOutput` | `test_workflows.py`, `test_grounding.py`; live evaluation (EXT-01, EXT-02: recall 1.0) | LIVE-TESTED |
| Multi-document comparison, contradiction vs context | `comparison.py`, `ComparisonOutput` | `test_workflows.py`, `test_grounding.py`; live evaluation (CMP-01, CMP-02) | LIVE-TESTED |
| Provider abstraction, timeouts, bounded retries, rate limits, cost, request limits, mock provider | `llm_client.py`, `offline_provider.py`, `model_catalog.py` | `test_llm_client.py`; live OpenAI runs | COMPLETE; OpenAI **LIVE-TESTED**; Anthropic and Gemini not live-verified |
| Security: .gitignore, .env.example, key protection, session isolation, no temp files, safe errors, content-free logs, injection defences, data disclosure | `security.py`, `.gitignore`, `.streamlit/config.toml`, sidebar | `test_security.py`, `test_app.py`, `scripts/verify_project.py` | COMPLETE for a single-server prototype; not tested as multi-tenant production |
| OCR | Not implemented (documented limitation) | n/a | Not in scope |
