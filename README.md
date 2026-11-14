# DocIntel AI

Ask questions about your PDFs and see the exact passages behind every answer.

DocIntel AI is a document intelligence assistant built for AAI-530 (Large Language Model Engineering).
Upload PDFs, then ask questions, summarize, extract structured information and compare documents.
Every answer cites passages from your documents, and the app independently checks each citation and
highlights the quoted words in the source, down to the original PDF page.

![Answer with highlighted evidence](assets/screenshots/01_ask_answer_with_evidence.png)

*Screenshots in this README were captured from the running app in **offline demo mode** (no API key),
where answers are sentences copied by a keyword method, not written by an AI model. They show the
interface, citations and checks, not LLM answer quality.*

## The problem

Contracts, reports, policies and research papers are long, and the facts people need are scattered
across pages and documents. A general chatbot answers fluently but does not show its sources, may
invent figures, cannot tell an amended term from a contradiction, and can be steered by instructions
hidden in a document. DocIntel keeps every answer tied to checkable evidence and says when the
documents do not contain an answer.

**Intended users:** students, researchers, analysts and business professionals who need to
understand long documents and verify what they will act on.

## Features

* **Grounded Q&A** with follow-up questions: answers only from your documents, with page-level
  citations, a status (answered, partly answered, not found, sources disagree), conflicts labelled as
  real contradictions or context differences, and facts separated from inferences.
* **Evidence panel:** cited passages with the quoted words highlighted; one click renders the original
  PDF page with the quote highlighted.
* **Citation checks:** every cited source ID must have been provided, every quote is matched against
  its passage, and a support heuristic checks the claim's terms and numbers. The app reports these
  checks honestly and never calls an answer "verified".
* **Summaries** (executive, detailed, findings, dates, action items, obligations, risks) using
  section-by-section map-reduce for long documents, with a page-coverage report.
* **Structured extraction** of people, organizations, dates, amounts, responsibilities, obligations,
  decisions, risks and key facts, each with source and quote; JSON download.
* **Comparison** of two to four documents: conflicts, numerical discrepancies, important changes,
  deadline differences, one-sided content and similarities.
* **Safety:** documents are treated as untrusted data; instruction-like text is flagged; fabricated
  citations and prompt leaks are detected; uploads are validated; no document leaves the session
  except the passages sent to the chosen model provider.
* **Model choice:** OpenAI (default), Anthropic or Google Gemini via configuration, plus an offline
  mode that needs no key.
* **Evaluation suite:** 40 labelled cases, a retrieval benchmark, cost-guarded live evaluation and a
  human review sheet.

| Prompt-injection document, flagged | Cited page with highlight |
|---|---|
| ![Injection flagged](assets/screenshots/03_injection_flagged_source.png) | ![Cited page](assets/screenshots/02_cited_page_highlight.png) |
| **Summary with coverage report** | **Structured extraction** |
| ![Summary](assets/screenshots/04_summary.png) | ![Extraction](assets/screenshots/05_extraction.png) |

## How it works

```text
PDF -> validate -> extract text per page (PyMuPDF, in memory) -> remove repeated headers/footers
    -> page-aware chunks -> hybrid search index (BM25 + character n-grams)
question -> retrieve top passages within a token budget -> versioned prompt with passages as
    untrusted <source id="S1" page="2"> blocks -> LLM returns schema-validated JSON with verbatim
    quotes -> citation checks -> answer + highlighted evidence
```

No database, vector store or agent framework: one Python package (`src/docintel`) and a Streamlit UI.
Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Model and API selection

| | |
|---|---|
| Provisional default | OpenAI `gpt-6-luna` (Responses API, strict JSON schema, `store=false`, reasoning effort `low`) |
| Price | USD 0.10 input / 0.50 output per million tokens; about **$0.15 per 100 typical requests** |
| Alternatives implemented | Anthropic `claude-haiku-5-5`, Google `gemini-3.1-flash-lite`, offline extractive baseline |
| Status | Chosen from official documentation (2026-11-13); **not yet benchmarked live** |

The comparison of 11 models, prices, data policies and the decision rule is in
[docs/API_SELECTION_REPORT.md](docs/API_SELECTION_REPORT.md).

## Installation

Requires Python 3.11 or newer (developed and tested on Python 3.14.4, macOS).

```bash
git clone https://github.com/shifrin-robert/AAI-530-LLM-Final-Project.git
cd AAI-530-LLM-Final-Project
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

On Windows, activate with `.venv\Scripts\activate`. Optional providers:
`pip install -e ".[anthropic,gemini]"`. To reproduce the exact tested environment instead:
`pip install -r requirements-lock.txt` followed by `pip install -e . --no-deps`.

## Configuration and API keys

```bash
cp .env.example .env
```

Edit `.env` and set the key for the provider you want (only one is needed):

```text
DOCINTEL_PROVIDER=openai
OPENAI_API_KEY=your-key-here
```

`.env` is git-ignored; never commit keys. Without a key the app starts in offline demo mode. All
settings (model, retries, timeouts, upload limits, chunking, retriever, prompt version) are documented
in [.env.example](.env.example).

## Run the app

```bash
streamlit run app.py
```

Then open http://localhost:8501 and click **Load sample documents** to try every feature with the
synthetic documents. See the [user guide](docs/USER_GUIDE.md).

## Tests and checks

```bash
python -m pytest
```

All 190 tests run offline in a few seconds: no network access, API keys or charges. Provider adapters
are tested against the real SDKs with mocked HTTP; the UI is tested headlessly with Streamlit's
AppTest.

```bash
python scripts/verify_project.py
```

The audit script runs linting, format checks, the tests, a secret scan and a check that no
`.env` files or non-synthetic PDFs would be committed.

## Evaluation

```bash
python -m evaluation.retrieval_eval
```

```bash
python -m evaluation.evaluation_runner --provider mock
```

These two run offline and for free. Live runs need a key and explicit permission to spend.
Set up the key and a hard spend limit with the
[live evaluation guide](docs/LIVE_EVALUATION_GUIDE.md) first:

```bash
python -m evaluation.evaluation_runner --provider openai --model gpt-6-luna --allow-paid --max-cost-usd 1
```

Results are written to `evaluation/results/`. Current measured results (retrieval benchmark and the
offline extractive baseline: 23 of 40 cases) and the pending live evaluation are reported in
[docs/EVALUATION_REPORT.md](docs/EVALUATION_REPORT.md).

## Repository structure

```text
app.py                       Streamlit interface
src/docintel/                Application package
  config.py                  Settings from environment variables
  model_catalog.py           Model IDs and verified prices
  models.py                  Data records and strict LLM output schemas
  pdf_processing.py          Validation, extraction, normalization, page rendering
  chunking.py                Page-aware deterministic chunking
  retrieval.py               BM25, character n-grams, hybrid, context selection
  prompting.py               Versioned prompt loading and rendering
  llm_client.py              Provider interface, OpenAI/Anthropic/Gemini adapters, retries, cost
  offline_provider.py        Offline extractive baseline
  grounding.py               Citation validation
  qa.py, summarization.py, extraction.py, comparison.py   Task workflows
  session.py, security.py, workflow_utils.py
prompts/                     Versioned prompt templates (QA v1 and v2, summary, extraction, comparison)
tests/                       190 automated tests (offline)
evaluation/                  Fixtures, labelled cases, runners, scoring, results
scripts/                     Cost estimate and project audit
docs/                        Documentation, appendix, evaluation, ethics, presentation materials
assets/screenshots/          Screenshots of the running app (offline demo mode)
```

## Documentation

| Document | Contents |
|---|---|
| [Project documentation](docs/PROJECT_DOCUMENTATION.md) | Full write-up (problem to conclusion) |
| [Architecture](docs/ARCHITECTURE.md) | Pipeline, modules, design decisions |
| [API selection report](docs/API_SELECTION_REPORT.md) | Providers, models, prices, data handling, decision |
| [Prompt and testing appendix](docs/PROMPT_AND_TESTING_APPENDIX.md) | Prompts, versions, schemas, cases, outputs, iterations |
| [Evaluation report](docs/EVALUATION_REPORT.md) | Method, measured results, pending runs |
| [Live evaluation guide](docs/LIVE_EVALUATION_GUIDE.md) | API key, spend limits and staged live runs |
| [AI use and ethical reflection](docs/AI_USE_AND_ETHICAL_REFLECTION.md) | AI tools, verification, risks |
| [User guide](docs/USER_GUIDE.md) | How to use every feature |
| [Presentation script](docs/PRESENTATION_SCRIPT.md), [demo walkthrough](docs/DEMO_WALKTHROUGH.md) | Recorded presentation materials |
| [Requirements traceability](docs/REQUIREMENTS_TRACEABILITY.md) | Course requirements mapped to evidence |
| [Team contributions](docs/TEAM_CONTRIBUTIONS.md) | Editable contribution record |

## Known limitations

* Live LLM behavior has not been evaluated yet (no API key was available during development).
* Lexical retrieval misses pure synonyms; embeddings are the planned next step.
* No OCR for scanned pages; complex tables may extract imperfectly.
* The citation support check is a heuristic, and the injection filter cannot catch every attack.
* Small synthetic evaluation set; results will not transfer directly to long real documents.
* A single-server prototype: no authentication or multi-tenant hardening.

## Security and privacy

Uploaded files stay in the browser session's memory and are never written to disk, cached across
sessions, logged or committed. With a hosted model, the question and the retrieved passages are sent
to the provider shown in the sidebar (OpenAI requests use `store=false`). Do not upload confidential
documents unless your organization allows that provider. Keys are read from `.env` only. Only
synthetic sample documents are included in this repository.

## AI-use disclosure

This project is at AIAS Level 4. ChatGPT supported planning, specification and review; Claude Code
(Anthropic) implemented the application, tests, evaluation tooling and documentation under human
direction. Details and the team's verification record:
[docs/AI_USE_AND_ETHICAL_REFLECTION.md](docs/AI_USE_AND_ETHICAL_REFLECTION.md).

## Team

Robert (architecture, integration, repository coordination), Josue (prompt engineering and testing),
Marie (evaluation, testing, safety and limitations). These are the proposed responsibilities; the
verified record is in [docs/TEAM_CONTRIBUTIONS.md](docs/TEAM_CONTRIBUTIONS.md).

## Future improvements

Run the live benchmark and prompt comparison; add embedding retrieval; optional OCR; semantic
citation checking; a larger independent evaluation set; prompt caching and streaming; authentication
for multi-user deployment.
