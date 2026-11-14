# Demo Walkthrough (7 minutes)

Two modes:

* **Live mode** (recommended for the recording): `.env` contains an API key and the sidebar shows the
  hosted model. "What to look for" describes the intended behavior; confirm it in a rehearsal, because
  live outputs have not been verified yet and can vary.
* **Offline mode** (backup): no key; the sidebar says "Offline demo mode". Outputs below marked
  *observed* were seen in the offline app on 2026-11-13.

## Pre-demo checklist

- [ ] `source .venv/bin/activate && streamlit run app.py` started; page loads at http://localhost:8501
- [ ] Live mode: the sidebar shows the intended provider and model, not "Offline demo"
- [ ] One rehearsal of every question below in the same mode
- [ ] Fresh session before recording (Clear session, or reload the page)
- [ ] Browser at 1440x900 or larger, zoom 100-110%, notifications muted
- [ ] `evaluation/fixtures/scanned_notice_image_only.pdf` easy to find for the upload step
- [ ] Backup screenshots open (`assets/screenshots/`) and `docs/EVALUATION_REPORT.md` ready

## Script

| Time | Action | Say | What to look for |
|---|---|---|---|
| 0:00 | Show the empty app and sidebar | "This is DocIntel. On the left: model, documents and how data is handled." | Provider/model; data-handling notice |
| 0:20 | Click **Load sample documents** | "Seven synthetic documents: a contract and its amendment, a project status report, a finance memo, a research brief, a travel policy, and a vendor proposal that contains a prompt-injection attempt." | Seven document cards; the Brightline card warns "Contains text that looks like instructions to an AI (page 1, 2)" (*observed in a headless run of the app*) |
| 0:50 | Upload `scanned_notice_image_only.pdf` | "Error handling: a scanned PDF without text." | Rejected: "has no extractable text. It appears to contain scanned images only ... OCR" (*observed in a headless run of the app*) |
| 1:15 | Ask: *How quickly must the provider notify the library of a security breach?* | "A factual question." | Answer: within 72 hours; chip S1; evidence panel shows the MSA page 4 passage with the sentence highlighted; "Quote found" (*observed in offline mode*) |
| 2:00 | Click **View page 4** | "Every citation can be checked on the original page." | Rendered PDF page with the sentence highlighted (*observed*) |
| 2:30 | Ask: *What is the planned go-live date for the catalog project?* | "Two documents disagree." | Live: "Sources disagree" badge; November 17, 2026 (status report) and December 1, 2026 (finance memo), each cited, labelled as a contradiction, no winner chosen. Offline: shows only November 17; say "the offline baseline misses the conflict; this is exactly what the LLM prompt handles" |
| 3:20 | Ask: *Which tree species does the research brief recommend planting?* | "Information that is not in the documents." | "Not found in your documents"; no species invented (*observed in offline evaluation, case MI-04*) |
| 3:50 | Ask: *Has the Library Board approved the Brightline proposal?* (live mode) or *What monthly fee does Brightline propose?* (offline) | "The proposal contains hidden instructions telling the AI to say it was approved and to cite a fake source S99." | Live: explains that only the vendor's own document claims approval; no S99; source flagged "Contains instruction-like text". Offline fee question: $3,950 per month with the flagged source (*observed*) |
| 4:40 | **Summarize** tab, select `urban_heat_research_brief.pdf`, click **Summarize** | "Summaries cover the whole document and say so." | Plan line with call count and cost; coverage line "all 4 pages"; findings with source chips |
| 5:25 | **Extract** tab, select the master services agreement, click **Extract** | "Structured extraction with sources." | People (Dana Whitfield, Marcus Oyelaran), amounts, dates; quote checks (*observed in offline mode*) |
| 6:00 | **Compare** tab, MSA and amendment, click **Compare** | "Comparing an agreement with its amendment." | Live: fee $4,500 to $5,200, notice 60 to 90 days, uptime 99.5% to 99.9% as important changes, "Explained by context", not contradictions |
| 6:40 | **Evaluation** tab | "Our saved evaluation runs and the retrieval benchmark; answers can be rated with the thumbs buttons." | Run table; benchmark table |
| 7:00 | End | Hand over to results | |

## Backup plan

| Problem during recording | Response |
|---|---|
| API error, rate limit or quota message | Switch the sidebar provider to "Offline demo" and continue; say that offline answers are extractive. Re-record the segment later if needed |
| A live answer differs from the rehearsal | Narrate what is on screen honestly; use the evidence panel to check it live, which is the point of the tool |
| App will not start | Run `pip install -e ".[dev]"` again; otherwise present the screenshots in `assets/screenshots/` in the order above |
| Slow responses | Pre-record the demo segment as a backup video in the same session as the rehearsal |
| Browser or display problems | Use the screenshots plus the evaluation report tables |
