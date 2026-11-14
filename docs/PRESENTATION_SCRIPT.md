# Presentation Script (10-15 minute recorded presentation)

No recording exists yet; the team records it. Timing target: **introduction 4:35** (limit 5:00),
**live demonstration 7:00** (minimum 5:00), **results and conclusion 2:30**, total about 14 minutes.
Speaker assignments follow the proposed responsibilities and can be swapped.

Two variants are marked where content depends on whether the live evaluation has been run before
recording: **[LIVE]** (use measured numbers from `evaluation/results/`) and **[OFFLINE]** (present
the offline results and say live results are pending). Never present estimates as results.

## Running order

| # | Segment | Speaker | Time |
|---|---|---|---|
| 1 | Title | Robert | 0:10 |
| 2 | The problem | Robert | 0:40 |
| 3 | Users and what DocIntel does | Robert | 0:25 |
| 4 | Architecture | Robert | 0:40 |
| 5 | API and model selection | Robert | 0:40 |
| 6 | Prompt engineering | Josue | 0:40 |
| 7 | Grounding and citation checks | Josue | 0:25 |
| 8 | Evaluation design | Marie | 0:30 |
| 9 | Responsible use | Marie | 0:25 |
| 10 | Live demonstration (see `DEMO_WALKTHROUGH.md`) | Robert drives; Josue and Marie narrate their parts | 7:00 |
| 11 | Results | Marie | 1:00 |
| 12 | Limitations | Marie | 0:30 |
| 13 | AI-assisted development | Josue | 0:30 |
| 14 | Future work and close | Robert | 0:30 |

## Slides and speaker notes

### Slide 1: DocIntel AI (0:10)
**On slide:** DocIntel AI. Grounded answers from your PDFs. AAI-530 Final Project. Robert, Josue, Marie.
**Notes:** "We built DocIntel AI, an assistant that answers questions about your documents and shows
you exactly where every answer comes from."

### Slide 2: The problem (0:40)
**On slide:** Long documents, scattered facts. Chatbots answer fluently but: no sources; invented
figures; amendments mistaken for contradictions; can be manipulated by text inside documents.
**Notes:** Use the sample case: a contract, its amendment, a status report and a finance memo that
disagree on the go-live date. "If you rely on the answer, you need to see the evidence."

### Slide 3: Users and features (0:25)
**On slide:** Students, researchers, analysts, business professionals. Ask, Summarize, Extract,
Compare, with page-level evidence.
**Notes:** One sentence per feature; the demo will show each.

### Slide 4: Architecture (0:40)
**On slide:** The pipeline diagram from `docs/ARCHITECTURE.md` (PDF, extraction, chunks, hybrid
search, versioned prompt, LLM with JSON schema, citation checks, highlighted evidence).
**Notes:** "Everything runs in one Python process. PDFs are processed in memory. We use a hybrid of
keyword and character n-gram search, which we benchmarked. Chunks never cross page boundaries, so
every citation maps to a page."

### Slide 5: API and model selection (0:40)
**On slide:** Table of the economy and mid-tier candidates with prices; "Provisional: OpenAI
gpt-6-luna, $0.15 per 100 typical requests"; Anthropic and Gemini adapters implemented.
**Notes:** "We compared eleven models from OpenAI, Anthropic and Google using official documentation.
GPT-6 Luna and Claude Haiku 5.5 tie on price; we chose Luna for strict JSON-schema decoding,
`store=false` and our team's familiarity. Switching providers is a configuration change."
[OFFLINE] "The choice is provisional until our live benchmark runs." [LIVE] state the measured
comparison and whether it confirmed the choice.

### Slide 6: Prompt engineering (0:40)
**On slide:** v1 (6 lines) vs v2 (11 sections): instruction hierarchy, documents as untrusted data,
verbatim quotes, fact vs inference, insufficient evidence, conflicts, ambiguity, confidence, safety.
JSON schema output.
**Notes (Josue):** "v1 just said 'use the sources and cite them'. Reviewing it against our test
categories showed gaps: nothing stopped instructions planted in a document, no way to answer part of
a question, no rule for conflicts. v2 adds those, and asks for a verbatim quote for every citation so
our code can check it." [LIVE] give the v1 vs v2 numbers. [OFFLINE] "The measured comparison is
ready to run; we have not run it yet."

### Slide 7: Grounding and citation checks (0:25)
**On slide:** Three separate checks: ID provided? Quote in passage? Claim supported (heuristic)?
"Passing checks is not proof."
**Notes:** "The app generates the source IDs. A model citing S99 is caught immediately. Quotes are
matched against the passage text, and the evidence panel highlights them."

### Slide 8: Evaluation design (0:30)
**On slide:** 40 labelled cases in 11 categories over synthetic PDFs; 12 paraphrase retrieval
questions; metrics: accuracy, abstention, conflicts, injection resistance, citation validity, quote
match, cost; 242 automated tests.
**Notes (Marie):** "Every reference answer is checked automatically against the actual PDF page, so
our labels can be verified."

### Slide 9: Responsible use (0:25)
**On slide:** Bring your own API key (per session, never shown or stored), in-memory only, no logs of
content, provider disclosure, `store=false`, injection defences, human verification disclaimer.
**Notes:** "The app supports a human reviewer; it does not replace one."

### Slide 10: Live demonstration (7:00)
Follow `docs/DEMO_WALKTHROUGH.md`.

### Slide 11: Results (1:00)
**On slide (measured now):** 242 tests pass. Retrieval: on paraphrased questions, keyword search got
the right page to the model 9/12 times, hybrid 11/12; one synonym question ("drinks" vs "alcoholic
beverages") defeats all lexical methods. Offline baseline: 23/40 cases; 0/3 conflicts; quoted an
injected instruction once.
**Notes:** "The baseline's failures show why an LLM with our prompts is needed, and why valid
citations are not the same as correct answers: it once cited a real sentence that did not answer the
question." [LIVE] add the LLM's metrics side by side with the baseline and name the failure cases.
[OFFLINE] "Live model results are pending; we will not estimate them."

### Slide 12: Limitations (0:30)
**On slide:** Live behavior unmeasured [OFFLINE]; synonyms; no OCR; heuristic checks; small synthetic
dataset; prototype security.

### Slide 13: AI-assisted development (0:30)
**On slide:** AIAS Level 4. ChatGPT: planning and review. Claude Code: implementation, tests,
documentation. Verification: tests, contract tests, benchmarks, visual review, our own review.
**Notes (Josue):** mention one concrete bug the tests caught (hyphenation corrupting
"cross-sectional", or the SDK dependency change) and what the team personally reviewed
**[TEAM TO CONFIRM]**.

### Slide 14: Future work and close (0:30)
**On slide:** Live benchmark and prompt comparison; embedding retrieval; OCR; semantic citation
checking; bigger independent test set.
**Notes:** "DocIntel turns citations into evidence you can check. Thank you."

## Recording tips

* Record at 1440x900 or larger, browser zoom 100-110%, sidebar visible.
* Rehearse the demo once with the exact questions; keep the timer visible.
* Start the app before recording and keep the backup screenshots open in another window.
