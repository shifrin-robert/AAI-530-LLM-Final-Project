# API Selection Report

**Status: PROVISIONAL.** The recommendation below is based on documented capabilities and verified
list prices.

* **Measured:** the recommended model, `gpt-6-luna`, was evaluated live on 2026-11-14 on the 40
  labelled cases. It passed 39 of 40 with prompt v2, scored automatically (Section 8).
* **Not measured:** the other models have not been benchmarked, so the comparison between models
  is still based on documentation and prices. Section 8 explains how to run the benchmark that would
  confirm or change the choice.

| | |
|---|---|
| Date of research | 2026-11-13 |
| Researched by | Claude Code (implementation assistant), from official provider documentation |
| Decision owner | The team (Robert, Josue, Marie), after the live benchmark |
| Recommended provider / model | **OpenAI `gpt-6-luna`**, reasoning effort `low` (provisional) |
| Escalation model if quality is insufficient | OpenAI `gpt-6.1-terra` |
| Implemented alternatives | Anthropic `claude-haiku-5-5`; Google `gemini-3.1-flash-lite`; offline extractive baseline |

> **Conflict-of-interest note.** This report was drafted by Claude Code, which is built on an
> Anthropic model, and Anthropic is one of the providers compared. To limit self-preference bias,
> every figure comes from the providers' own pages (cited below), the selection criteria were fixed
> before comparing, and the final choice is left to the team after a measured benchmark. The
> team's stated preliminary preference was OpenAI; the evidence below does not overturn it.

---

## 1. Requirements the model must meet

DocIntel sends a system prompt, up to ~8 retrieved passages and a question, and needs back a JSON
object (answer, claims with verbatim quotes, conflicts, missing information) that our code validates.
The criteria, in priority order:

1. **Reliable structured output** (JSON-schema adherence) so every response can be validated.
2. **Instruction following and grounding**: answer only from sources, cite given IDs, abstain when
   evidence is missing, report conflicts instead of resolving them, ignore instructions inside documents.
3. **Cost** for an academic project (hundreds to low thousands of calls).
4. **Data handling** suitable for documents users may consider private.
5. **Context window** of at least ~30k tokens (our requests are 4k-18k tokens).
6. **Latency, rate limits, SDK quality, ease of switching models.**

## 2. Providers and models compared

Prices are USD per 1 million tokens, standard (non-batch) tier, as listed on the official pricing
pages on 2026-11-13. "Cached" is the price for cached input tokens.

### OpenAI ([pricing](https://developers.openai.com/api/docs/pricing), [models](https://developers.openai.com/api/docs/models))

| Model ID | Input | Cached input | Output | Context / max output | Reasoning effort options | Status |
|---|---|---|---|---|---|---|
| `gpt-6-luna` | 0.10 | 0.01 | 0.50 | 1,050,000 / 128K | none, low, medium (default), high, xhigh, max | current |
| `gpt-5.6-luna` | 0.20 | 0.02 | 1.20 | 1,050,000 / 128K | none ... max | current |
| `gpt-6.1-terra` | 1.00 | 0.05 | 5.00 | 1,050,000 / 128K | none ... max | current |
| `gpt-6.1-sol` | 2.00 | 0.10 | 10.00 | 1,050,000 / 128K | low ... max | current |
| `gpt-6-astra` (flagship) | 10.00 | 1.00 | 50.00 | 1,050,000 / 128K | low ... max (no `none`) | current |
| `gpt-5-mini` / `gpt-5-nano` | 0.25 / 0.05 | - | 2.00 / 0.40 | 400K / 128K | - | deprecated, shutdown 2026-12-11 |
| `gpt-4.1-mini` | 0.40 | 0.10 | 1.60 | 1,047,576 / 32,768 | non-reasoning | deprecated, shutdown 2027-01-14 |

All current models above list Structured Outputs support. `gpt-6-luna` has a May 18, 2026 knowledge
cutoff; `gpt-6.1-terra` June 1, 2026 (model pages). Entry ("Build") tier rate limits: 5,000 requests
per minute and 2,000,000 tokens per minute for the Luna models ([rate limits](https://developers.openai.com/api/docs/guides/rate-limits)).

### Anthropic ([pricing](https://platform.claude.com/docs/en/about-claude/pricing), [models](https://platform.claude.com/docs/en/about-claude/models/overview))

| Model ID | Input | Cache hit | Output | Context / max output | Status |
|---|---|---|---|---|---|
| `claude-haiku-5-5` (prompts up to 100k tokens) | 0.10 | 0.01 | 0.50 | 1M / 128K | active |
| `claude-haiku-5-5` (prompts over 100k tokens) | 0.50 | 0.05 | 2.50 | 1M / 128K | active |
| `claude-sonnet-5-5` | 2.00 | 0.10 | 10.00 | 1M / 128K | active |
| `claude-opus-5-5` | 4.00 | 0.20 | 20.00 | 1M / 128K | active |
| `claude-haiku-4-5-20251001` (previous generation) | 1.00 | 0.10 | 5.00 | 200K / 64K | active |

Native JSON-schema structured outputs (`output_config.format`) are documented as stable and available
on all current models ([structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)).
Entry ("Start") tier limits for Haiku 5.5: 4,000 RPM, 2,000,000 input and 400,000 output tokens per
minute ([rate limits](https://platform.claude.com/docs/en/api/rate-limits)).

### Google Gemini ([pricing](https://aistudio.google.com/docs/pricing), [models](https://aistudio.google.com/docs/models))

| Model ID | Input | Cached | Output (incl. thinking) | Context / max output | Free tier | Status |
|---|---|---|---|---|---|---|
| `gemini-3.1-flash-lite` | 0.25 | 0.025 | 1.50 | 1,048,576 / 65,536 | yes | stable |
| `gemini-3.5-flash-lite` | 0.30 | 0.03 | 2.50 | 1,048,576 / 65,536 | yes | stable |
| `gemini-3.8-flash` | 0.75 (1.50 from 2027-01-01) | 0.075 | 3.75 (7.50 from 2027-01-01) | 1,048,576 / 65,536 | yes | stable |
| `gemini-4-hydrogen` | 1.50 | 0.075 | 7.50 | 1,048,576 / 65,536 | yes | stable |
| `gemini-2.5-flash-lite` (older) | 0.10 | 0.01 | 0.40 | - | yes | served "until further notice" |

Structured output via `response_mime_type="application/json"` plus `response_json_schema`
([structured output](https://aistudio.google.com/docs/structured-output)). Thinking defaults:
Flash-Lite models "On (minimal)", 3.8 Flash "On (medium)" ([thinking](https://aistudio.google.com/docs/thinking)).
Per-model rate limits for the free and Tier 1 levels are shown only inside AI Studio and could not be
verified from the public pages.

## 3. Structured-output capabilities (documented)

| | OpenAI | Anthropic | Google |
|---|---|---|---|
| Mechanism | Responses API `text.format = {type: json_schema, strict: true}`; SDK `responses.parse(text_format=Model)` | `output_config.format = {type: json_schema, schema}`; SDK `messages.parse(output_format=Model)` | `response_json_schema` + `response_mime_type` |
| Schema rules that affect us | all fields required; optional values as `X \| null`; `additionalProperties: false` | no numeric/string length constraints; `additionalProperties` must be false | length constraints ignored; very large schemas may be rejected |
| Implemented in DocIntel | yes (`OpenAIProvider`) | yes (`AnthropicProvider`) | yes (`GeminiProvider`) |
| Verified offline against the real SDK (mocked HTTP) | yes | yes | yes |
| Verified against the live API | **no** | **no** | **no** |

DocIntel's schemas (`src/docintel/models.py`) were written to satisfy the strictest of these rules
(every field required, no defaults, `additionalProperties: false`), so the same Pydantic models work
with all three providers. All outputs are re-validated by Pydantic and by the citation checker
regardless of provider.

## 4. Data handling (documented policies)

| | OpenAI API | Anthropic API | Gemini API |
|---|---|---|---|
| Used for training by default | No ([your data](https://developers.openai.com/api/docs/guides/your-data)) | No ([privacy center](https://privacy.claude.com/en/articles/7996868-is-my-data-used-for-model-training)) | **Free tier: yes**, used to improve products and may be read by human reviewers; paid tier: no ([terms](https://aistudio.google.com/docs/terms)) |
| Default retention | Abuse-monitoring logs up to 30 days | Inputs/outputs deleted within 30 days (exceptions for policy enforcement) ([retention](https://privacy.claude.com/en/articles/7996866-how-long-do-you-store-my-organization-s-data)) | Paid: logged "for a limited period"; free: not stated |
| Response storage | Responses API **stores responses by default (`store` defaults to true)**; DocIntel always sends `store=false` | not applicable | not applicable |
| Zero data retention | By approval | By agreement | not documented for this tier |
| Notes | | | Free tier warns not to submit sensitive, confidential or personal information; apps serving EEA/UK/Switzerland must use paid services |

**Consequence for DocIntel:** any of the three paid APIs is acceptable for the synthetic demo
documents. For real documents, users must still follow their organization's rules, and the app tells
them what is sent and to whom. The Gemini free tier is only appropriate for synthetic test data.

## 5. Cost estimate for 100 typical requests

Computed by `python scripts/estimate_costs.py` from the price catalog in `src/docintel/model_catalog.py`.

**Workload assumptions** (planning estimates, ~4 characters per token, no caching or batch discounts):

| Request type | Share | Input tokens each | Output tokens each (incl. reasoning) |
|---|---|---|---|
| Grounded Q&A (v2 system prompt ~1.3k + 8 passages ~2.1k + question/schema ~0.6k) | 70 | 4,000 | 800 |
| Summary of a ~20-page document (2 map calls + 1 reduce) | 15 | 17,400 | 3,600 |
| Extraction from a ~20-page document (2 section calls) | 10 | 14,000 | 3,000 |
| Comparison of two documents | 5 | 10,000 | 1,500 |
| **Total per 100 requests** | | **731,000** | **147,500** |

| Provider | Model | Tier | Input $/1M | Output $/1M | Cost per 100 requests | Per request |
|---|---|---|---|---|---|---|
| OpenAI | `gpt-6-luna` | economy | 0.10 | 0.50 | **$0.15** | $0.0015 |
| Anthropic | `claude-haiku-5-5` | economy | 0.10 | 0.50 | **$0.15** | $0.0015 |
| OpenAI | `gpt-5.6-luna` | economy | 0.20 | 1.20 | $0.32 | $0.0032 |
| Google | `gemini-3.1-flash-lite` | economy | 0.25 | 1.50 | $0.40 | $0.0040 |
| Google | `gemini-3.5-flash-lite` | economy | 0.30 | 2.50 | $0.59 | $0.0059 |
| Google | `gemini-3.8-flash` | mid | 0.75 | 3.75 | $1.10 | $0.0110 |
| OpenAI | `gpt-6.1-terra` | mid | 1.00 | 5.00 | $1.47 | $0.0147 |
| OpenAI | `gpt-6.1-sol` | mid | 2.00 | 10.00 | $2.94 | $0.0294 |
| Anthropic | `claude-sonnet-5-5` | mid | 2.00 | 10.00 | $2.94 | $0.0294 |
| Anthropic | `claude-opus-5-5` | frontier | 4.00 | 20.00 | $5.87 | $0.0587 |
| OpenAI | `gpt-6-astra` | frontier | 10.00 | 50.00 | $14.69 | $0.1469 |

Reasoning tokens are billed as output. If `gpt-6-luna` at effort `low` produced, say, 3x the assumed
output tokens, the 100-request cost would still be under $0.40. The full 40-case evaluation suite is
estimated at well under $0.25 per run on the economy models (the runner prints a conservative estimate
and refuses to start without `--allow-paid`).

## 6. Advantages and disadvantages

| Option | Advantages | Disadvantages |
|---|---|---|
| **OpenAI `gpt-6-luna`** | Lowest price tier; strict JSON-schema decoding with first-class Python helper; `store=false` control; very high entry rate limits; reasoning effort adjustable down to `none`; team preference and familiarity | Reasoning model: hidden reasoning tokens add cost/latency (mitigated with `low`); Responses API stores data unless `store=false` is sent; not benchmarked yet |
| OpenAI `gpt-6.1-terra` | Stronger model family member at moderate cost | 10x the price of Luna |
| Anthropic `claude-haiku-5-5` | Same price as Luna for our prompt sizes; native structured outputs; 30-day deletion by default | Price jumps 5x for prompts over 100k tokens (not our case); no sampling-parameter control in the current API; not benchmarked |
| Google `gemini-3.1-flash-lite` | Free tier allows zero-cost experiments with synthetic data; 1M context | 2.5-3x Luna's price on the paid tier; free tier data is used for product improvement and human review; rate limits not publicly listed |
| Offline extractive baseline | Free, deterministic, private; makes the app demonstrable without keys | Not an LLM: no synthesis, conflict detection or real abstention (see evaluation) |

## 7. Recommendation and justification

**Provisional choice: OpenAI `gpt-6-luna` with reasoning effort `low`, called through the Responses
API with strict structured outputs and `store=false`.**

1. **Cost-effectiveness:** tied for the cheapest current model ($0.15 per 100 typical requests), which
   leaves room for repeated evaluation runs and the prompt-iteration experiment.
2. **Structured-output reliability:** strict JSON-schema decoding is the property our validation
   pipeline depends on most; OpenAI documents it as a first-class feature with a typed SDK helper.
3. **Data handling:** API data is not used for training by default and storage can be disabled per
   request, which the app does.
4. **Team fit:** the team's preliminary preference; tied with Anthropic Haiku 5.5 on price and with no
   measured evidence favoring either, the preference is a legitimate tie-breaker.
5. **Low switching cost:** the provider is one setting (`DOCINTEL_PROVIDER` / `DOCINTEL_MODEL`), so if
   the benchmark favors Haiku 5.5 or Terra, switching requires no code change.

**Why not the most expensive model?** Our task is narrow: read ~8 passages and answer with citations.
Mid and frontier models cost 10-100x more; they should be adopted only if the benchmark shows the
economy model failing on our categories (multi-page reasoning, conflicts, abstention).

## 8. Model benchmarking (one model measured; comparison pending)

The same 40 labelled cases, settings and prompt versions are used for every model:

```bash
# 1. Put OPENAI_API_KEY (and optionally ANTHROPIC_API_KEY) in .env, then:
python -m evaluation.evaluation_runner --provider openai --model gpt-6-luna --allow-paid --max-cost-usd 1
python -m evaluation.evaluation_runner --provider openai --model gpt-6.1-terra --allow-paid --max-cost-usd 2
python -m evaluation.evaluation_runner --provider anthropic --model claude-haiku-5-5 --allow-paid --max-cost-usd 1
python -m evaluation.compare_runs evaluation/results/<run_a>.json evaluation/results/<run_b>.json
```

Each run records answer accuracy, citation validity, quote match rate, heuristic support, correct
abstention, conflict handling, injection resistance, schema compliance (format errors), latency,
actual token usage and cost. Add `--repeats 3` to measure consistency and `--judge` for an LLM-judged
citation-support check (spot-check it by hand).

**Decision rule for the team:** keep `gpt-6-luna` if its overall pass rate is within 5 percentage
points of the best model tested and it has no injection failures; otherwise move to the cheapest model
that meets that bar.

**Measured results (2026-11-14 and 2026-11-15, one model).** `gpt-6-luna` was scored automatically; no result has
been human-reviewed. Full results are in `docs/EVALUATION_REPORT.md`, Sections 5, 7.3 and 7.5.

| Run | Passed | Notes |
|---|---|---|
| Prompt v2 | 39 / 40 | No errors |
| Prompt v1 | 37 / 40 | Not significantly different from v2 |
| Prompt v2, 3 repeats | 116 / 120 | Outcome agreement 0.95 |
| Prompt v3 (the default since 2026-11-15), 3 runs | 119 / 120 | Fixed CF-02 in 3 of 3 runs; same list-price cost as v2 |
| Generalization set: v2 and v3, 3 runs each | 26 / 30 and 30 / 30 | 10 new cases; v3 passed all 6 dated-spending runs, v2 passed 2 |

* **Schema and citations:** schema-valid output in all 383 live case runs, and no fabricated citation
  ID or prompt-canary leak.
* **Speed:** mean latency about 4 seconds; up to 21 seconds for extraction.
* **Cost:** $0.0127 per 40-case run with prompt v2, computed from token counts. Prompt v3 adds
  about 120 input tokens per question, roughly $0.0004 per 40-case run at list prices.
* **Decision rule:** it cannot be applied until a second model is run. No other model has been
  tested, so `gpt-6-luna` has not been shown to be better than any alternative.

## 9. Documented versus verified

| Claim | Documented by provider | Verified by this project |
|---|---|---|
| Prices, context windows, policies above | yes (pages cited) | read on 2026-11-13; may change |
| Request/response format of each adapter | yes | **yes, offline**: tests run each adapter against the real SDK with mocked HTTP responses (`tests/test_llm_client.py`) |
| JSON-schema adherence in practice | yes | **yes, for `gpt-6-luna`**: schema-valid output in 203 of 203 live case runs; other models not tested |
| Grounding, abstention, conflict and injection behavior | no | **Partly**: measured for `gpt-6-luna` on 40 synthetic cases with automatic scoring, not human-reviewed (`docs/EVALUATION_REPORT.md` Sections 5 and 6) |
| Latency and real token usage | no | **yes, for `gpt-6-luna`**: mean 3.9 s per case (prompt v2); 411,087 input and 87,445 output tokens over 203 case runs |
