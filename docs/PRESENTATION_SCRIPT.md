# Presentation Script (10-15 minute recorded presentation)

No recording exists yet; the team records it. Timing target: **introduction 4:35** (limit 5:00),
**live demonstration 7:00** (minimum 5:00), **results and conclusion 2:30**, total about 14 minutes.
Speaker assignments follow the proposed responsibilities and can be swapped.

The live evaluation was run on 2026-11-14, so the results slide uses its measured numbers from
`docs/EVALUATION_REPORT.md`. Never present estimates as results. Always say that the scores are
automatic and not human-reviewed, unless the team finishes the human review before recording; in
that case use its results.

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
Add: "We measured Luna live: it passed 39 of 40 benchmark cases with prompt v2, with schema-valid
output every time. We have not benchmarked other models yet, so the choice is still provisional."

### Slide 6: Prompt engineering (0:40)
**On slide:**

* v1 (6 lines) vs v2 (11 sections): instruction hierarchy, documents as untrusted data, verbatim
  quotes, fact vs inference, insufficient evidence, conflicts, ambiguity, confidence, safety. JSON
  schema output.
* v3 = v2 plus one rule: give every figure reported as of a different date, each with its date.
* v3 is the default.
**Notes (Josue):** "v1 just said 'use the sources and cite them'. Reviewing it against our test
categories showed gaps: nothing stopped instructions planted in a document, no way to answer part of
a question, no rule for conflicts. v2 adds those, and asks for a verbatim quote for every citation so
our code can check it. Measured live, v1 passed 37 of 40 and v2 39 of 40. That difference is too
small to be significant. v2 kept failing one case, where it dropped an earlier spending figure, so
v3 adds one rule for figures reported on different dates. It fixed that case, and the same failure
on new documents, without breaking anything else. That is why v3 is now the default."

### Slide 7: Grounding and citation checks (0:25)
**On slide:** Three separate checks: ID provided? Quote in passage? Claim supported (heuristic)?
"Passing checks is not proof."
**Notes:** "The app generates the source IDs. A model citing S99 is caught immediately. Quotes are
matched against the passage text, and the evidence panel highlights them."

### Slide 8: Evaluation design (0:30)
**On slide:** 40 labelled cases in 11 categories over synthetic PDFs; 12 paraphrase retrieval
questions; metrics: accuracy, abstention, conflicts, injection resistance, citation validity, quote
match, cost; 307 automated tests.
**Notes (Marie):** "Every reference answer is checked automatically against the actual PDF page, so
our labels can be verified."

### Slide 9: Responsible use (0:25)
**On slide:** Bring your own API key (per session, never shown or stored), in-memory only, no logs of
content, provider disclosure, `store=false`, injection defences, human verification disclaimer.
**Notes:** "The app supports a human reviewer; it does not replace one."

### Slide 10: Live demonstration (7:00)
Follow `docs/DEMO_WALKTHROUGH.md`.

### Slide 11: Results (1:00)
**On slide (measured, automatic scoring):**

* 307 tests pass.
* Retrieval: on paraphrased questions, keyword search got the right page to the model 9 of 12
  times, hybrid 11 of 12. One synonym question ("drinks" vs "alcoholic beverages") defeats every
  lexical method.
* End to end, on 40 cases: the offline baseline passed 23. GPT-6 Luna passed 37 with prompt v1 and
  39 with prompt v2 (38, 40 and 38 in three more runs).
* Prompt v3, a targeted revision and now the default, fixed the one case v2 kept failing:
  * benchmark: 119 of 120 against v2's 116 of 120 over three runs, with CF-02 passing 3 of 3;
  * 10 new cases written to test it: 30 of 30 against 26 of 30;
  * spending reported on two dates: 6 of 6 against 2 of 6;
  * no case got worse.
* These are automatic scores on synthetic documents; none is human-verified, and they are not
  accuracy on arbitrary documents.
* In 383 live case runs: no fabricated citation and no prompt leak; every missing-information case
  abstained correctly. Total cost $0.099.

**Notes (Marie):** "The baseline's failures show why an LLM with our prompts is needed. The live
model fixes most of them. Its one real failure is CF-02: asked how much has been spent to date, it
usually gave only the latest figure, although both figures were in its context. It passed once in
four tries. Our scoring audit found two automatic rules that were too strict. For example, an answer
that quoted an injected instruction in order to warn about it was counted as obeying it. So we
report the original and the revised scores side by side, and no result file was changed. Prompts v1
and v2 differ by one or two cases, which is not statistically significant. We then wrote prompt v3,
which adds a single rule for figures reported on different dates. It fixed CF-02 in all three runs.
We set its pass criteria before running it, and it met all four. One case can't prove a rule, so
we wrote 10 new cases with new documents, and fixed the criteria before running them. v3 passed all
30 runs and v2 passed 26. v3 kept every figure from different dates, still flagged both real
contradictions, and didn't invent conflicts between figures that agree. It met all five criteria,
so we made it the default. These samples are small and the runs repeat the same questions, so the
difference isn't statistically significant. None of this has been reviewed by a person yet; the
review worksheet is ready."

### Slide 12: Limitations (0:30)
**On slide:** One model measured, scored automatically, not yet human-reviewed; small synthetic
datasets (v3's gain rests on three similar cases); synonyms; no OCR; heuristic checks; prototype
security.

### Slide 13: AI-assisted development (0:30)
**On slide:** AIAS Level 4. ChatGPT: planning and review. Claude Code: implementation, tests,
documentation. Verification: tests, contract tests, benchmarks, visual review, our own review.
**Notes (Josue):** mention one concrete bug the tests caught (hyphenation corrupting
"cross-sectional", or the SDK dependency change) and what the team personally reviewed
**[TEAM TO CONFIRM]**.

### Slide 14: Future work and close (0:30)
**On slide:** Human review; team-written cases over real documents; other models; embedding
retrieval; OCR;
semantic citation checking; bigger independent test set.
**Notes:** "DocIntel turns citations into evidence you can check. Thank you."

## Recording tips

* Record at 1440x900 or larger, browser zoom 100-110%, sidebar visible.
* Rehearse the demo once with the exact questions; keep the timer visible.
* Start the app before recording and keep the backup screenshots open in another window.
