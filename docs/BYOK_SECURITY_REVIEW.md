# Bring Your Own Key: Security Review

This review covers how DocIntel AI handles provider API keys, done on 2026-11-14 for the
bring-your-own-key (BYOK) change. It covers what was reviewed, what was found, what changed, which
tests guard each point, and what remains out of scope. Streamlit's per-session state is treated as
one layer, not as proof of multi-user security.

## Before this change

There was no BYOK. The sidebar listed the providers whose keys were set in the server's environment
or `.env`, and every browser session used those keys. In any shared deployment, every visitor would
have spent the developer's credit. Two more weaknesses sat behind that:

* `Settings.from_env()` loaded `.env` with `load_dotenv`, which copied the developer's keys into
  `os.environ`, where any library could pick them up.
* The provider adapters looked keys up in `os.environ` themselves.

## How keys work now

| Mode | Set by | Key used for a browser session |
|---|---|---|
| `byok` (default) | nothing to set | Only the key that session entered. Server keys are never used, even when `OPENAI_API_KEY` and the others are set |
| `owner` | `DOCINTEL_KEY_MODE=owner` | The session's own key if it entered one, otherwise the server's key, billed to the server owner. Only for the owner's local use or an authorized private deployment |

Keys reach a provider adapter through one path:
`resolve_credential(provider, settings, session_store)` in `src/docintel/credentials.py`, then
`create_provider(settings, credential=...)`. The adapters never read the environment for keys, and a
hosted provider cannot be built without a credential. The command-line evaluation runner is the key
owner's own tool, so it passes the server key explicitly (`server_credential`), and only with
`--allow-paid`.

## Review findings and fixes

| # | Where a key could leak | Finding | Fix | Guarded by |
|---|---|---|---|---|
| 1 | Fallback to the developer's key | Every session used server keys | BYOK by default; owner mode must be set explicitly | `test_byok_never_uses_the_servers_key`, `test_byok_never_falls_back_to_the_server_key`, `test_owner_mode_uses_the_server_key_and_a_users_own_key_takes_precedence` |
| 2 | Process environment | `load_dotenv` copied `.env` keys into `os.environ` | `.env` is read into a dictionary (`read_dotenv`); nothing is written to `os.environ` | `test_reading_dotenv_never_copies_values_into_the_process_environment`; UI tests assert a session key never appears in `os.environ` |
| 3 | Provider adapters | Adapters fetched keys from `os.environ` | Adapters accept only an explicit `Credential`; wrong-provider credentials are refused | `test_factory_raises_without_key_when_fallback_disabled`, `test_a_key_entered_for_one_provider_is_never_used_for_another` |
| 4 | SDK client construction | The SDKs read server settings even when given a key (next section) | Session keys get sealed clients; settings that can't be overridden block session keys | `test_*_session_key_client_ignores_the_server_environment`, `test_session_keys_are_refused_while_unoverridable_sdk_settings_are_set` |
| 5 | Shared caches and globals | None found: no `st.cache_data`/`st.cache_resource`, no module-level mutable state in `app.py` or `src/` | Keys and the SDK clients that hold them live only in `st.session_state` | `test_keys_are_isolated_between_sessions_and_never_global`, which scans every `docintel` module's globals |
| 6 | Provider cache | Cached clients were keyed by provider and model only | The cache key includes the credential source; the cache is emptied when a key is set, removed or cleared | `test_removing_the_key_drops_it_and_the_client_that_held_it`, `test_clear_session_also_removes_keys` |
| 7 | Widget state | A typed key stays in the text field's state | A form with `clear_on_submit`; the submit callback moves the key into the store and blanks the field | `test_a_key_for_another_provider_is_refused_without_being_shown` (fails if the blanking line is removed) |
| 8 | Display | n/a (new UI) | Password field; the sidebar shows provider, model and whose key, never any part of the key | Every UI test scans all rendered text and widget values for the key |
| 9 | Error messages | Providers echo part of a rejected key (for example OpenAI's "Incorrect API key provided: user-s...0001") | Fixed messages; SDK exceptions are not chained (`from None`) | `test_key_check_errors_are_clear_and_never_echo_the_key`, `test_unusable_keys_are_refused_without_echoing_them` |
| 10 | Logs | DocIntel logs counts and kinds only. SDK debug logging (`OPENAI_LOG`, `ANTHROPIC_LOG`) would log request content | Session keys are refused while SDK debug logging is on | as #4 |
| 11 | Wrong provider | A pasted key could be sent to the wrong company | Recognizable foreign prefixes (`sk-ant-`, `sk-proj-`, `AIza`, ...) are refused before anything is sent | `test_unusable_keys_are_refused_without_echoing_them`, `test_a_key_for_another_provider_is_refused_without_being_shown` |
| 12 | Evaluation artifacts | The runner never had session keys; result files store a fixed list of settings | Unchanged; now tested | `test_runner_uses_the_owners_server_key_and_never_writes_it` |
| 13 | URLs, browser storage, disk | `st.query_params` is unused; no custom JavaScript; nothing is written to disk | The key field sets `autocomplete="off"` | review |
| 14 | Screenshots | The committed screenshots were taken in offline mode with no key | Keys are never displayed (#8) | review |

## Provider SDKs and the server environment

These SDK versions are installed; each constructor was read line by line.

| SDK | Server settings it would apply to a user's request | How DocIntel handles them for session keys |
|---|---|---|
| openai 3.51.0 | `OPENAI_BASE_URL`, `OPENAI_ORG_ID`, `OPENAI_PROJECT_ID`, `OPENAI_ADMIN_KEY` | Explicit `https://api.openai.com/v1`; `organization`, `project` and `admin_api_key` cleared after construction (an empty string would still send the header) |
| | `OPENAI_CUSTOM_HEADERS`, `OPENAI_LOG` | Always read, so session keys are refused while either is set |
| anthropic 2.8.0 | `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, profiles, workload identity | Not consulted when `api_key` is passed explicitly (documented in the SDK, and tested with all of them set) |
| | `ANTHROPIC_BASE_URL` | Explicit `https://api.anthropic.com` |
| | `ANTHROPIC_CUSTOM_HEADERS`, `ANTHROPIC_LOG`, `ANTHROPIC_OPEN_TELEMETRY_TRACES_CONTENT_MODE=content` | Session keys are refused while any is set |
| google-genai 3.3.0 | `GEMINI_API_KEY`, `GOOGLE_API_KEY` | Not used when `api_key` is passed |
| | `GOOGLE_GENAI_USE_VERTEXAI`, `GOOGLE_GENAI_USE_ENTERPRISE` | `vertexai=False` passed explicitly |

The sealing tests set all of these variables to fake values and capture the HTTP request each SDK
actually builds. They assert three things:
* the request goes to the official endpoint;
* only the session key appears in the credential header;
* no server value appears anywhere in the URL or headers.

The Anthropic test also showed that anthropic 2.8 sends the key as `Authorization: Bearer`, not
`x-api-key`. Owner mode (server keys) keeps the SDKs' normal behavior, because the operator's
environment is theirs to configure.

## Errors users see

| Situation | Message (never contains the key) |
|---|---|
| No key for the selected provider | Offline demo notice: "Enter your OpenAI API key above to use it." |
| Malformed or wrong-provider key | "That looks like an Anthropic key, so it was not used or sent anywhere..." and similar |
| Invalid, revoked or expired key (OpenAI and Anthropic 401; Gemini 401/403 or 400 `API_KEY_INVALID`) | "OpenAI rejected the API key. It may be mistyped, revoked or expired." |
| Key not allowed to use the model | "...not permitted to use this model" / "...not available to your ... account" |
| Credit or spend limit exhausted | OpenAI: billing codes (`insufficient_quota`, `credit_balance_exhausted`, `*_spend_limit_exceeded`). Anthropic: messages about credit balance or usage limits. Both are reported as quota errors and not retried |
| Unsafe server SDK setting | "This server sets OPENAI_CUSTOM_HEADERS, which the OpenAI SDK would apply to requests made with your key... nothing was sent." |

## Key check

**Check key** calls the provider's model-information endpoint:
* OpenAI: `GET /v1/models/{model}`.
* Anthropic: `GET /v1/models/{id}`.
* Gemini: `models.get`.

It generates no text and uses no tokens, but it does count toward the provider's rate limits and this
session's request budget, and the interface says so. A key that passes can still fail later if the
account has no credit or reaches a spend limit, because a model lookup doesn't consume credit; the
interface says that too.

## Verification

* **Tests:** 242 automated tests pass offline (`python -m pytest`). 52 of them are new for BYOK:
  * `tests/test_credentials.py`: 23, covering precedence, scoping, the store, removal and format checks;
  * `tests/test_llm_client.py`: sealed clients, key checks, errors;
  * `tests/test_app.py`: 9 headless UI sessions, covering isolation, display, removal, owner mode,
    the key check, clear session and unsafe settings;
  * `tests/test_config.py` and `tests/test_evaluation_dataset.py`: `.env` handling and the runner.
* **Mutation check:** eight safeguards were removed one at a time to confirm a test fails. The
  safeguards were the explicit endpoints (OpenAI, Anthropic), clearing the organization, the Gemini
  Vertex switch, the owner-mode gate, the unsafe-settings refusal, the clear-session wipe and the
  key-field blanking. Seven failed at once. The key-field blanking was not caught at first; a test
  for the refused-key case was added, and now all eight fail when their safeguard is removed.
* **Audit:** `python scripts/verify_project.py` passes 6/6, including its secret scan.
* **Live browser check (2026-11-14):** in the running app, a fake test key was entered and removed.
  The key never appeared in the page text, HTML, input values, URL, localStorage, sessionStorage or the
  server log.
* **Not done:** no request was sent to a real provider; the tests use the real SDKs against a mocked
  HTTP transport.

## Remaining limitations

* **Server memory.** A user's key lives in the Streamlit server's memory for as long as the session
  exists, including a short time after the tab closes until Streamlit discards the session. Anyone
  who controls the server process (the operator, a debugger, memory dumps or swap) could read it.
  Python cannot reliably wipe strings from memory. Users must trust the operator.
* **Transport.** Keys travel from the browser to the server over Streamlit's websocket. A hosted
  deployment must use HTTPS, and TLS-terminating proxies under the operator's control can see the
  traffic. Proxy and certificate settings (`HTTPS_PROXY`, `SSL_CERT_FILE`) are infrastructure and
  outside this review.
* **Isolation is per session in one process.** It relies on Streamlit's `st.session_state` plus the
  absence of shared caches and globals (tested). There is no authentication, per-user rate limiting
  or audit logging, and no multi-server or high-concurrency testing. This is not a multi-tenant
  security guarantee.
* **SDK upgrades.** The sealing was verified for openai 3.51, anthropic 2.8 and google-genai 3.3.
  After upgrading, rerun the tests (they inspect real SDK requests) and reread the constructors for
  new environment variables.
* **Heuristics.** Anthropic billing detection matches message phrases. The foreign-prefix check
  can't recognize every format; Google documents no prefix for its newer auth keys.
* **Browser.** `autocomplete="off"` is a hint; a password manager may still offer to save the key.
* **Owner mode.** Whether users are authorized to bill the owner's account is the operator's
  decision; the app cannot verify it.
