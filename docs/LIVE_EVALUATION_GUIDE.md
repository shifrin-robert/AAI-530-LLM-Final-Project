# Live Evaluation Guide

This guide covers setting up the OpenAI API for DocIntel AI, capping what it can spend, and running
the live evaluation in stages.

**Status:** costs below are computed from token counts.

* **2026-11-14:** the core plan below (Steps 6 and 7a to 7c) was run for $0.056.
* **2026-11-15:** the prompt v3 test was run for $0.032, and the generalization set for v2 and v3
  for $0.011. v3 then became the default prompt.
* **Results:** in [EVALUATION_REPORT.md](EVALUATION_REPORT.md), Sections 5, 7.3 and 7.5.
* **Not yet run:** the human review (7d) and the other models.
* **Prompt versions in the commands:** every command below passes `--prompt-version` explicitly,
  so each earlier run can be reproduced exactly. Without the flag, the runner uses v3.

OpenAI dashboard labels below come from OpenAI's documentation, checked on 2026-11-14 (sources at
the end). Screens change; if a label differs, look for the closest match.

## What it will cost

Before calling the API, the runner prints a conservative estimate. It assumes 6,000 input and 1,500
output tokens per case and uses the prices verified on 2026-11-13. These are estimates, not
measurements:

| Run | Extra flags | Estimate |
|---|---|---|
| Smoke test, 3 cases | `--cases DF-01,MI-04,INJ-02` | $0.004 |
| Full run, prompt v2, 40 cases | `--prompt-version v2` | $0.054 |
| Full run, prompt v1, 40 cases (prompt comparison) | `--prompt-version v1` | $0.054 |
| Consistency, prompt v2, 40 cases x 3 | `--repeats 3` | $0.162 |
| **Core plan total** | | **about $0.27** |
| Optional: mid-tier `gpt-6.1-terra`, 40 cases | `--model gpt-6.1-terra` | $0.54 |
| Optional: Anthropic `claude-haiku-5-5` (needs an Anthropic key) | `--provider anthropic` | $0.054 |
| Optional: Google `gemini-3.1-flash-lite` (needs a Gemini key) | `--provider gemini` | $0.15 |

These estimates leave out two costs:

* `--judge` adds one model call per case.
* Questions asked in the app while rehearsing the demo are extra. They cost about $0.15 per 100
  typical requests on `gpt-6-luna` (see `scripts/estimate_costs.py`).

Real costs can be higher or lower than the estimate, because reasoning tokens are billed as output
tokens. Each run file records the cost calculated from the token counts the API returned. The
OpenAI Usage page shows what was actually billed.

## Safety layers

| Layer | What it stops | Where it is set |
|---|---|---|
| Prepaid credit, auto-recharge off | Any spending beyond the balance you bought | OpenAI billing |
| Hard monthly spend limit on a dedicated project | Spending beyond the limit by this project's keys | OpenAI project limits |
| `--allow-paid` | Paid calls that were not explicitly requested | DocIntel runner |
| `--max-cost-usd` | A run whose estimate is above the cap. It is checked once before the first call and does not track spending during the run | DocIntel runner |
| Stop on account errors | Further calls after a bad key, unknown model or spend limit; no results file is written | DocIntel runner |
| Request cap per browser session | More than 200 model requests from one app session | `DOCINTEL_MAX_REQUESTS_PER_SESSION` |
| Offline tests | `python -m pytest` never reads `.env` and never calls an API | `tests/conftest.py` |
| Bring your own key | The app never uses the `.env` key unless owner mode is on, so a shared deployment can't spend it | `DOCINTEL_KEY_MODE` |

OpenAI says spend-limit enforcement is not instantaneous, so recorded spend can slightly exceed a
limit. The prepaid balance and the hard limit are the real ceilings. The runner's checks only
prevent mistakes.

## Step 1. Create a dedicated project

1. Sign in at https://platform.openai.com with the account that will pay.
2. Use the project selector to create a project for the course, for example `DocIntel AAI-530`. It
   gets its own keys, spend limit and usage history.
3. Invite the teammates who will run evaluations to the project. Each person then creates their
   own key, as OpenAI recommends ("Don't share one developer's key across a team").

## Step 2. Add a small prepaid credit and turn off auto-recharge

1. Open Billing: https://platform.openai.com/settings/organization/billing
2. Add the smallest credit amount offered. OpenAI's help center lists a $5 minimum and says
   auto-recharge is on by default during setup.
3. Turn auto-recharge off. The balance is then a ceiling: once it is used up, requests fail with
   `credit_balance_exhausted` until you add more.

## Step 3. Set a hard spend limit on the project

1. Open project settings (https://platform.openai.com/settings/), select the project, then open
   **Limits**.
2. In **Spend**, select **Edit spend limit**.
3. Set **Monthly spend limit** to $3 and **Alert when spend reaches** to $1.
4. Turn on **Enforce a hard limit**, then select **Save**.

An alert alone does not stop traffic; only **Enforce a hard limit** does. You can add the same
limit for the whole organization at https://platform.openai.com/settings/organization/limits.

When a limit is reached, OpenAI returns HTTP 429 with `project_spend_limit_exceeded` (or
`organization_spend_limit_exceeded`). DocIntel shows "OpenAI stopped the request because a spend
limit, usage limit or the prepaid credit balance was reached" and does not retry.

## Step 4. Create a project API key

1. Open API keys (https://platform.openai.com/api-keys) and choose **Create new secret key**.
2. Create it in the `DocIntel AAI-530` project and give it your name, for example
   `docintel-robert-laptop`.
3. Choose permissions. **All** is acceptable inside this capped project. If you choose
   **Restricted** and a permission is missing, the smoke test shows "not permitted to use this
   model or endpoint".
4. If an expiration date is offered, set it to the end of the term.
5. Copy the key when it is shown; OpenAI does not show the full key again.

Never paste the key into a chat (including ChatGPT or Claude), an email, a screenshot, a document
or a commit. If a key leaks, revoke it on the API keys page immediately, create a new one and check
the Usage page.

## Step 5. Put the key in `.env`

```bash
cp .env.example .env
```

Open `.env` in an editor and set:

```text
DOCINTEL_PROVIDER=openai
DOCINTEL_MODEL=gpt-6-luna
OPENAI_API_KEY=<paste the key here>
```

The command-line evaluation runner reads this key. The app ignores it unless you also set
`DOCINTEL_KEY_MODE=owner` (Step 8), so a shared deployment never spends your key.

Check that git ignores the file:

```bash
git check-ignore -v .env
```

It should print the rule that ignores the file (`.gitignore:2:.env`), and `git status` must not list
`.env`. The test suite stays offline with the key present: `python -m pytest` should still report
307 passed.

## Step 6. Dry run (free)

```bash
python -m evaluation.evaluation_runner --provider openai
```

It prints `Planned: 40 cases x 1 repeat(s) on gpt-6-luna; conservative cost estimate $0.0540.` and
stops with exit code 2, because `--allow-paid` is missing. Nothing is sent.

## Step 7. Run in stages, only after spending is authorized

Run the commands from the project folder with the virtual environment active. If a line shows
`ERROR`, stop and investigate before the next step.

### 7a. Smoke test (3 cases)

The output goes to the git-ignored scratch folder, so it can't be mistaken for a result:

```bash
python -m evaluation.evaluation_runner --provider openai --cases DF-01,MI-04,INJ-02 --allow-paid --max-cost-usd 0.05 --out evaluation/results/scratch --tag smoke
```

Expect three `PASS` or `FAIL` lines, no `ERROR`, and about a cent or less on the Usage page.

### 7b. Prompt comparison

Use the same model, cases and settings for both runs, then compare them:

```bash
python -m evaluation.evaluation_runner --provider openai --prompt-version v2 --allow-paid --max-cost-usd 0.25 --tag live-v2
```

```bash
python -m evaluation.evaluation_runner --provider openai --prompt-version v1 --allow-paid --max-cost-usd 0.25 --tag live-v1
```

```bash
python -m evaluation.compare_runs evaluation/results/<run>_v1_live-v1.json evaluation/results/<run>_v2_live-v2.json
```

### 7c. Consistency (v2, three repeats)

```bash
python -m evaluation.evaluation_runner --provider openai --prompt-version v2 --repeats 3 --allow-paid --max-cost-usd 0.5 --tag live-v2-x3
```

### 7d. Human review sheet

The worksheet is pre-filled with the v2 answers and the outcome of each v2 repeat. The reviewer
columns are left blank. It is written to `evaluation/human_review/`; instructions are in the
`README.md` there:

```bash
python -m evaluation.make_review_sheet evaluation/results/<run>_v2_live-v2.json --repeats evaluation/results/<run>_v2_live-v2-x3.json
```

### 7e. Scoring audit (free)

Re-score the saved runs with the original and the proposed revised rules. The audit only reads
`evaluation/results/` and writes to `evaluation/audit/`:

```bash
python -m evaluation.scoring_audit
```

### Prompt v3 test (run on 2026-11-15)

Prompt v3 adds one rule for figures reported as of different dates (case CF-02). It is not the
default and the app does not offer it. It was run with this command, under a separate $0.50
authorization; the conservative estimate was $0.162 and it cost $0.032:

```bash
python -m evaluation.evaluation_runner --provider openai --prompt-version v3 --repeats 3 --allow-paid --max-cost-usd 0.5 --tag live-v3-x3
```

### Generalization set (run on 2026-11-15)

These are 10 new cases, separate from the benchmark, that test whether v3's rule generalizes. v2
and v3 were each run on them three times. The conservative estimate was $0.081 and the actual cost
$0.011. v2 passed 26 of 30 case runs and v3 passed 30 of 30. The commands, the criteria fixed in
advance and the results are in `evaluation/generalization/README.md`. Results are in
`evaluation/results/generalization/`.

### Optional model benchmark

Add `--model gpt-6.1-terra --max-cost-usd 1` to compare a mid-tier model. Anthropic and Gemini need
their own keys and the same billing precautions with those providers.

## Step 8. Rehearse the demo with the live model

```bash
streamlit run app.py
```

Give the app the key in one of two ways:

* **Paste it into the sidebar** (**Your OpenAI API key**, then **Use this key**). This is how every
  other user of the app works, and the key lasts only for that browser session.
* **Owner mode, on your own computer only:** add `DOCINTEL_KEY_MODE=owner` to `.env` and restart. The
  app then uses the `.env` key for sessions without their own key. Never use owner mode on a shared
  deployment.

The sidebar should show "Active model: OpenAI GPT-6 Luna" and whose key is in use, not "Offline demo
mode". **Check key** confirms the key with one model-information request, which uses no tokens.

* Each question is one model request.
* Summaries and extractions of long documents make several requests, and the app shows the plan and
  estimated cost first.
* Switch the sidebar provider to "Offline demo" whenever you don't need the live model.

## What is sent to OpenAI

Each request sends the question, the prompt and the retrieved passages. During the evaluation those
passages come only from the synthetic fixture PDFs. OpenAI states that API data is not used for
training unless you opt in, and that it keeps abuse-monitoring logs for up to 30 days. DocIntel
sends `store=false`, so responses are not stored for later retrieval. In the app, upload only
documents you are allowed to share with OpenAI.

## Keeping live and offline results separate

* Each run writes `evaluation/results/<UTC time>_<provider>_<model>_<prompt>[_<tag>].json` and a
  matching `.md`.
  * Offline runs are named `..._offline_extractive-baseline_...`; live runs start
    `..._openai_gpt-6-luna_...`.
  * The metadata records `"offline"`, the model, settings, git commit and package versions.
  * The app's Evaluation tab shows the model and an "Offline baseline" column for every run.
* Never edit, rename or delete a result file, including the committed offline ones. Smoke runs go to
  `evaluation/results/scratch/`, which git ignores.
* In `docs/EVALUATION_REPORT.md`, leave Section 4 (offline baseline) unchanged.
  * Put live numbers in Section 5, copied from the generated `.md` files, with the run file name
    next to each table.
  * Report errors and failures exactly as they happened.
* Commit the live run files together with the report update. They contain synthetic document text,
  model outputs and token counts, never the key.

## Troubleshooting

| Message | Cause | What to do |
|---|---|---|
| `Refusing to call a paid API without --allow-paid` | Dry run | Add `--allow-paid` once spending is authorized |
| `Estimated cost exceeds --max-cost-usd` | The plan is above your cap | Run fewer cases, or raise the cap deliberately |
| `Cannot start: OPENAI_API_KEY is not set` | `.env` is missing, misnamed or not in the project folder | Repeat Step 5 |
| `OpenAI rejected the API key` | The key is wrong, revoked or expired | Create a new key (Step 4) |
| `not permitted to use this model or endpoint` | Restricted key, or no access to the model in the project | Widen the key's permissions or check the project's model access |
| `Model 'gpt-6-luna' was not found or is not available` | Wrong model ID, or no access on this account | Check the model list in the dashboard; agree on any model change with the team |
| `OpenAI stopped the request because a spend limit ...` | The hard limit or the credit balance was reached | The run stopped and wrote no file; add credit or raise the limit deliberately |
| `rate limit reached` | Too many requests per minute | DocIntel already retried; wait a minute and rerun |

## When Claude Code runs it for you

Give an explicit authorization in the chat, for example: "Authorized: OpenAI live evaluation, steps
7a to 7d, up to $1 total." The runner reads the key from `.env`, so Claude Code never needs to see
it. Never paste the key into the conversation.

## Sources (checked 2026-11-14)

* Spend limits: https://developers.openai.com/api/docs/guides/spend-limits
* API keys and service accounts: https://developers.openai.com/api/docs/guides/api-keys
* Rate limits and usage tiers: https://developers.openai.com/api/docs/guides/rate-limits
* Data controls: https://developers.openai.com/api/docs/guides/your-data
* Prepaid billing (help center): https://help.openai.com/en/articles/8264644-how-can-i-set-up-prepaid-billing.
  The page could not be loaded automatically; the $5 minimum and the auto-recharge default come
  from its search summary, so confirm them on the billing page.
