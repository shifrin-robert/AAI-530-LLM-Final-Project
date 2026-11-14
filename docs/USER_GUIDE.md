# User Guide

## 1. Start the app

```bash
source .venv/bin/activate        # after following the installation steps in README.md
streamlit run app.py
```

Open the address Streamlit prints (usually http://localhost:8501). Without an API key the app runs in
**offline demo mode**: answers are sentences copied from your documents by a keyword method, not
written by an AI model. To use a hosted model, enter your own API key in the sidebar (next section).

## 1a. Use your own API key

Each person uses their own key, and **usage is billed to the account that owns the key**.

1. Create a key with the provider you want:
   * OpenAI: https://platform.openai.com/api-keys
   * Anthropic: https://platform.claude.com/settings/keys
   * Google Gemini: https://aistudio.google.com/apikey

   Setting a spend limit first is a good idea; see the
   [live evaluation guide](LIVE_EVALUATION_GUIDE.md) for OpenAI.
2. In the sidebar, choose the **Model provider** and **Model**, paste the key into **Your ... API
   key**, and select **Use this key**. The field is cleared and the key is never shown again.
3. Optionally select **Check key**. It sends one model-information request to the provider, which
   confirms the key works and can use the selected model. No text is generated, so it uses no
   tokens, but it does count toward the provider's rate limits. A key that passes can still fail
   later if the account runs out of credit or reaches a spend limit.
4. The sidebar shows the active provider and model, and whose key is in use. It never shows the key.
5. Select **Remove key** to delete it from the session. **Clear everything** and closing the tab also
   delete it.

The key is kept in this browser session's memory on the server and is used only for the provider you
entered it for. It is never written to disk, `.env`, logs, URLs or browser storage, and other users of
the same app never see or use it. A key that looks like another provider's (for example an Anthropic
key pasted for OpenAI) is refused and not sent anywhere.

**Running the app only for yourself?** You can put your key in `.env` instead and set
`DOCINTEL_KEY_MODE=owner`, so you don't have to paste it each time. Never use owner mode on a shared
or public deployment: every visitor would spend your credit.

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

* **Model provider / Model**: OpenAI, Anthropic, Google Gemini or Offline demo. Hosted providers
  need your API key (section 1a); the model list shows prices per million tokens.
* **Answer settings**: prompt version (v2 default, v1 baseline for comparison), search method (hybrid
  default, keyword BM25, character n-grams) and passages per answer.
* **Clear session** removes all documents, answers, ratings and API keys from this browser session.

## 9. Privacy

Files stay in this session's memory and disappear when you clear the session or close the tab. With a
hosted model, the question and the retrieved passages (for summaries and extraction, the selected
documents' text) are sent to the provider shown in the sidebar, together with your API key. Do not
upload confidential documents unless your organization allows it. Your key stays in this session only
(section 1a).

## 10. Troubleshooting

| Problem | What to do |
|---|---|
| "Offline demo mode" with a hosted provider selected | Enter your key for that provider in the sidebar. Keys in `.env` are used only with `DOCINTEL_KEY_MODE=owner` |
| "looks like an Anthropic key" (or OpenAI, Google) | You pasted another provider's key: choose the matching provider or paste the right key |
| "rejected the API key. It may be mistyped, revoked or expired." | Remove the key, then paste it again or create a new one |
| "not permitted to use this model" or "not available to your ... account" | Choose another model, or check the key's project permissions with the provider |
| "This server sets ..." | The server's configuration would mix its own settings into your requests. The operator must remove the named setting |
| "a spend limit, usage limit or the prepaid credit balance was reached" | Add credit or raise the spend limit in the provider console ([live evaluation guide](LIVE_EVALUATION_GUIDE.md)) |
| "rate limit reached" | Wait a minute and retry; the app already retried a few times |
| "reached its request limit" | Clear the session or raise `DOCINTEL_MAX_REQUESTS_PER_SESSION` |
| "the response was cut off" | Ask a narrower question, or raise `DOCINTEL_MAX_OUTPUT_TOKENS` |
| A page cannot be searched | It is probably scanned; run OCR in a PDF tool and upload again |
