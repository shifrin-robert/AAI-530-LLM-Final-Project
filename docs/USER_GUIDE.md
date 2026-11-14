# User Guide

## 1. Start the app

```bash
source .venv/bin/activate        # after following the installation steps in README.md
streamlit run app.py
```

Open the address Streamlit prints (usually http://localhost:8501). Without an API key the app runs in
**offline demo mode**: answers are sentences copied from your documents by a keyword method, not
written by an AI model. To use a hosted model, copy `.env.example` to `.env`, add your key (for
example `OPENAI_API_KEY=...`) and restart.

## 2. Add documents

* **Add PDFs** in the sidebar (up to 10 files, 20 MB and 300 pages each, by default), or click
  **Load sample documents** to load seven synthetic test documents.
* Each document card shows its pages and searchable passages. Hover the help icon to see processing
  notes (for example, repeated headers that were removed).
* Warnings you may see:
  * *No extractable text on page(s) ...*: those pages are images (scanned). DocIntel does not run OCR,
    so questions about them cannot be answered.
  * *Contains text that looks like instructions to an AI*: the document includes phrases such as
    "ignore previous instructions". It is still searchable, but treated strictly as document content.
* Files that are rejected say why: not a PDF, corrupted, password-protected (remove the password
  first), too large, too many pages, or scanned with no text.

## 3. Ask questions (Ask tab)

1. Type a question in your own words. With the sample documents loaded you can click an example.
2. Use **Searching all documents** to limit the search to some documents.
3. Read the answer. Its badge tells you what kind of answer it is:
   * **Answered from your documents** / **Partly answered**
   * **Not found in your documents**: the documents do not contain it; DocIntel does not guess.
   * **Sources disagree**: each version is shown with its source; DocIntel does not pick a winner.
     A note says whether it looks like a real contradiction or a difference explained by context
     (dates, versions, amendments).
4. Check the **Evidence** panel on the right:
   * Chips like **S2** in the answer match the source cards.
   * The quoted words are highlighted in yellow inside each passage.
   * **Quote found / Close match / Quote not in passage** tell you whether the quoted words really
     appear in the cited passage.
   * The top badge summarizes all checks. "Cited quotes found in the sources" means the checks
     passed; it does **not** prove the answer is right. Read the passages.
   * **View page N** opens the original PDF page with the quote highlighted.
   * **Diagnostics** shows the model, prompt version, search method, tokens, time and cost.
5. Ask follow-up questions; DocIntel uses the previous question to find the right passages.
   Earlier answers are never treated as evidence.
6. Rate answers with the thumbs buttons (used in the Evaluation tab).

## 4. Summarize

Choose one or more documents and, optionally, a focus ("obligations and deadlines"). Before running,
the app shows how many model calls it will make and an estimated cost. Long documents are summarized
section by section and then combined; the result states whether every page was covered. You get an
executive summary, a detailed summary, key findings, dates, action items, obligations and risks, each
with source chips, plus a JSON download.

## 5. Extract

Choose documents and the kinds of information to extract (people, organizations, dates, amounts,
responsibilities, obligations, decisions, risks, key facts). Results appear as tables with the exact
value, details (or "not stated"), a normalized form, the source page and a quote check. Download the
result as JSON.

## 6. Compare

Choose two to four documents and, optionally, a focus. Findings are grouped into conflicts, numerical
discrepancies, important changes, obligation and deadline differences, other differences, content
found in only one document, and similarities. Each finding cites its sources; conflicts are labelled
"Contradiction", "Explained by context" or "Unclear".

## 7. Evaluation and About tabs

* **Evaluation**: your session's answer ratings (downloadable), saved evaluation runs, and the
  retrieval benchmark.
* **About**: how the pipeline works, the current model and its price, and the limitations.

## 8. Settings (sidebar)

* **Model provider / Model**: providers appear when their key is set in `.env`; the model list shows
  prices per million tokens.
* **Answer settings**: prompt version (v2 default, v1 baseline for comparison), search method (hybrid
  default, keyword BM25, character n-grams) and passages per answer.
* **Clear session** removes all documents, answers and ratings from this browser session.

## 9. Privacy

Files stay in this session's memory and disappear when you clear the session or close the tab. With a
hosted model, the question and the retrieved passages (for summaries and extraction, the selected
documents' text) are sent to the provider shown in the sidebar. Do not upload confidential documents
unless your organization allows it.

## 10. Troubleshooting

| Problem | What to do |
|---|---|
| "Offline demo mode" although you added a key | Check the variable name in `.env` (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY` or `GEMINI_API_KEY`) and restart the app |
| "rejected the API key" | The key is wrong or revoked |
| "a spend limit, usage limit or the prepaid credit balance was reached" | Add credit or raise the spend limit in the provider console ([live evaluation guide](LIVE_EVALUATION_GUIDE.md)) |
| "rate limit reached" | Wait a minute and retry; the app already retried a few times |
| "reached its request limit" | Clear the session or raise `DOCINTEL_MAX_REQUESTS_PER_SESSION` |
| "the response was cut off" | Ask a narrower question, or raise `DOCINTEL_MAX_OUTPUT_TOKENS` |
| A page cannot be searched | It is probably scanned; run OCR in a PDF tool and upload again |
