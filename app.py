"""DocIntel AI: Streamlit interface.

Run with:  streamlit run app.py

Every browser session gets its own DocumentWorkspace in st.session_state. Uploaded files are
kept in memory only and are never placed in Streamlit's cross-session caches.
"""

from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT / "src") not in sys.path:  # allows `streamlit run app.py` without an editable install
    sys.path.insert(0, str(ROOT / "src"))

import streamlit as st  # noqa: E402

from docintel import PRODUCT_NAME, __version__  # noqa: E402
from docintel.comparison import compare_documents  # noqa: E402
from docintel.config import FIXTURES_DIR, ConfigError, Settings, get_api_key  # noqa: E402
from docintel.extraction import CATEGORY_LABELS, extract_information, plan_extraction  # noqa: E402
from docintel.grounding import CitationCheck, GroundingReport  # noqa: E402
from docintel.llm_client import LLMError, LLMProvider, create_provider  # noqa: E402
from docintel.model_catalog import (  # noqa: E402
    DEFAULT_MODEL_BY_PROVIDER,
    VERIFIED_ON,
    get_model_info,
    models_for_provider,
)
from docintel.models import EXTRACTION_CATEGORIES, SourcePassage  # noqa: E402
from docintel.pdf_processing import render_page_png  # noqa: E402
from docintel.prompting import ConversationTurn  # noqa: E402
from docintel.qa import QAResult, answer_question  # noqa: E402
from docintel.security import GENERIC_ERROR, configure_logging, get_logger  # noqa: E402
from docintel.session import DocumentWorkspace  # noqa: E402
from docintel.summarization import plan_summary, summarize_documents  # noqa: E402
from docintel.workflow_utils import WorkflowError  # noqa: E402

configure_logging()
log = get_logger("app")

st.set_page_config(
    page_title="DocIntel AI",
    page_icon=":material/find_in_page:",
    layout="wide",
    initial_sidebar_state="expanded",
)

PROVIDER_LABELS = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "gemini": "Google Gemini",
    "mock": "Offline demo (no API calls)",
}
SAMPLE_FILES = [
    "larkspur_master_services_agreement.pdf",
    "larkspur_amendment_no1.pdf",
    "catalog_project_status_q3_2026.pdf",
    "catalog_finance_memo_oct_2026.pdf",
    "urban_heat_research_brief.pdf",
    "staff_travel_policy.pdf",
    "brightline_vendor_proposal.pdf",
]
EXAMPLE_QUESTIONS = [
    "What is the monthly service fee in the master services agreement?",
    "What is the planned go-live date for the catalog project?",
    "Which tree species does the research brief recommend planting?",
    "Has the Library Board approved the Brightline proposal?",
]
STATUS_BADGES = {
    "answered": ("Answered from your documents", "green"),
    "partially_answered": ("Partly answered", "blue"),
    "insufficient_evidence": ("Not found in your documents", "orange"),
    "conflicting_evidence": ("Sources disagree", "violet"),
}
VERDICT_BADGES = {
    "grounded": ("Cited quotes found in the sources", "green"),
    "review": ("Review these citations", "orange"),
    "unsupported": ("Citations could not be verified", "red"),
    "abstained": ("No citations to check", "gray"),
}
QUOTE_BADGES = {
    "exact": ("Quote found", "green"),
    "approximate": ("Close match", "blue"),
    "not_found": ("Quote not in passage", "orange"),
    "missing": ("No quote given", "gray"),
}
NATURE_LABELS = {
    "direct_contradiction": ("Contradiction", "red"),
    "context_difference": ("Explained by context", "blue"),
    "not_a_conflict": ("Not a conflict", "gray"),
    "unclear": ("Unclear", "orange"),
}
CATEGORY_TITLES = {
    "conflict": "Conflicts",
    "numerical_discrepancy": "Numerical discrepancies",
    "important_change": "Important changes",
    "obligation_or_deadline_difference": "Obligation and deadline differences",
    "difference": "Other differences",
    "missing_information": "Covered by only one document",
    "similarity": "Similarities",
}
CHECK_HELP = (
    "For every citation DocIntel checks three things separately: the source ID was really given to "
    "the model; the quoted words appear in that passage; and (a rough heuristic) the claim's key "
    "terms and numbers appear in the cited text. Passing these checks does not prove the answer is "
    "right. Read the highlighted passages."
)

STYLE = """
<style>
.di-subtitle { font-size: 1.06rem; color: #3B4659; margin: -0.4rem 0 0.2rem 0; max-width: 46rem; }
.di-chip { display: inline-block; padding: 0 0.42em; margin: 0 0.08em; border-radius: 5px;
  background: #E6ECFA; color: #1D3F8F; font-weight: 600; font-size: 0.82em; line-height: 1.55;
  white-space: nowrap; }
.di-mark { background: #FFE58A; color: inherit; padding: 0 0.12em; border-radius: 2px; }
.di-passage { font-size: 0.93rem; line-height: 1.58; color: #26303F; white-space: pre-wrap; }
.di-answer { font-size: 1rem; line-height: 1.6; color: #1B2333; }
.di-answer ul { margin: 0.3rem 0 0.3rem 1.2rem; }
.di-meta { color: #4A5568; font-size: 0.86rem; }
</style>
"""


# --------------------------------------------------------------------------- helpers


def md(text: str) -> str:
    """Escape text for st.markdown: '$' would otherwise start LaTeX math (breaks dollar amounts)."""
    return (text or "").replace("\\", "\\\\").replace("$", "\\$")


def chip_html(source_id: str) -> str:
    return f'<span class="di-chip">{html.escape(source_id)}</span>'


_INLINE_REF = re.compile(r"\[\s*(S\d+(?:\s*[,;]\s*S\d+)*)\s*\]")
_BULLET = re.compile(r"^[-*•]\s+")


def answer_html(text: str) -> str:
    """Escape model text and turn [S1, S2] markers into chips; keep simple bullet lists."""
    lines = (text or "").strip().splitlines()
    out: list[str] = []
    in_list = False
    for line in lines:
        escaped = html.escape(line.strip())
        escaped = _INLINE_REF.sub(
            lambda m: "".join(chip_html(s) for s in re.findall(r"S\d+", m.group(1))), escaped
        )
        if _BULLET.match(line.strip()):
            if not in_list:
                out.append("<ul>")
                in_list = True
            item = _BULLET.sub("", escaped)
            out.append(f"<li>{item}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        out.append(f"<p>{escaped}</p>" if escaped else "")
    if in_list:
        out.append("</ul>")
    return f'<div class="di-answer">{"".join(out)}</div>'


def highlight_html(passage_text: str, quotes: list[str]) -> str:
    """Escape a passage and wrap the quoted spans in highlighter marks (case/space-insensitive)."""
    text = re.sub(r"\n{2,}", "\n", passage_text)
    spans: list[tuple[int, int]] = []
    for quote in quotes:
        words = [re.escape(w) for w in re.findall(r"\S+", quote.strip(" \"'.…"))]
        if len(words) < 2:
            continue
        pattern = re.compile(r"[\s\-]*".join(words), re.IGNORECASE)
        match = pattern.search(text)
        if match:
            spans.append(match.span())
    spans.sort()
    pieces, cursor = [], 0
    for start, end in spans:
        if start < cursor:
            continue
        pieces.append(html.escape(text[cursor:start]))
        pieces.append(f'<mark class="di-mark">{html.escape(text[start:end])}</mark>')
        cursor = end
    pieces.append(html.escape(text[cursor:]))
    return f'<div class="di-passage">{"".join(pieces)}</div>'


def show_error(exc: BaseException) -> None:
    if isinstance(exc, WorkflowError | LLMError):
        st.error(exc.user_message, icon=":material/error:")
    else:
        log.error("unexpected_error type=%s", type(exc).__name__)
        st.error(GENERIC_ERROR, icon=":material/error:")


def stats_caption(stats) -> str:
    if stats is None:
        return "No model call was needed."
    usage = stats.usage
    parts = [
        f"{stats.provider}:{stats.model}",
        f"{stats.latency_s:.1f} s",
        f"{usage.input_tokens:,} in / {usage.output_tokens:,} out tokens"
        + (" (estimated)" if usage.estimated else ""),
    ]
    if stats.cost_usd is not None:
        parts.append("free (offline)" if stats.cost_usd == 0 else f"about ${stats.cost_usd:.4f}")
    if stats.attempts > 1:
        parts.append(f"{stats.attempts} attempts")
    return ", ".join(parts)


# --------------------------------------------------------------------------- session state


def init_state() -> None:
    defaults = {
        "messages": [],
        "selected_turn": None,
        "ratings": {},
        "providers": {},
        "processed_uploads": set(),
        "uploader_key": 0,
        "upload_messages": [],
        "summary_result": None,
        "extraction_result": None,
        "comparison_result": None,
        "page_cache": {},
        "pending_question": None,
        "turn_counter": 0,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    if "base_settings" not in st.session_state:
        try:
            st.session_state.base_settings = Settings.from_env()
            st.session_state.config_error = None
        except ConfigError as exc:
            st.session_state.base_settings = Settings(provider="mock")
            st.session_state.config_error = str(exc)
    if "workspace" not in st.session_state:
        st.session_state.workspace = DocumentWorkspace(st.session_state.base_settings)


def clear_session() -> None:
    st.session_state.workspace.clear()
    for key in ("messages", "upload_messages"):
        st.session_state[key] = []
    for key in (
        "summary_result",
        "extraction_result",
        "comparison_result",
        "selected_turn",
        "pending_question",
    ):
        st.session_state[key] = None
    st.session_state.ratings = {}
    st.session_state.page_cache = {}
    st.session_state.processed_uploads = set()
    st.session_state.uploader_key += 1  # resets the file uploader widget


def get_provider(settings: Settings) -> tuple[LLMProvider, str | None]:
    key = (settings.provider, settings.resolved_model, settings.reasoning_effort)
    cache = st.session_state.providers
    if key not in cache:
        status = create_provider(settings, allow_offline_fallback=True)
        cache[key] = (status.provider, status.fallback_reason)
    return cache[key]


def load_samples() -> None:
    ws: DocumentWorkspace = st.session_state.workspace
    added = 0
    for name in SAMPLE_FILES:
        result = ws.add_pdf(name, (FIXTURES_DIR / name).read_bytes())
        added += 1 if result.ok and not result.duplicate else 0
        if result.error:
            st.session_state.upload_messages.append(("error", result.error))
    st.session_state.upload_messages.append(("success", f"Loaded {added} sample document(s)."))


# --------------------------------------------------------------------------- sidebar


def sidebar() -> tuple[Settings, LLMProvider, str | None]:
    base: Settings = st.session_state.base_settings
    ws: DocumentWorkspace = st.session_state.workspace
    with st.sidebar:
        st.markdown(f"### {PRODUCT_NAME}")
        st.caption(f"Version {__version__}. Grounded answers from your PDFs.")
        if st.session_state.config_error:
            st.error(st.session_state.config_error)

        # ---- model
        available = [p for p in ("openai", "anthropic", "gemini") if get_api_key(p)] + ["mock"]
        preferred = base.provider if base.provider in available else available[0]
        provider_name = st.selectbox(
            "Model provider",
            available,
            index=available.index(preferred),
            format_func=lambda p: PROVIDER_LABELS[p],
            help="Providers appear here when their API key is set in your .env file.",
        )
        model = DEFAULT_MODEL_BY_PROVIDER[provider_name]
        if provider_name != "mock":
            options = [m.model_id for m in models_for_provider(provider_name)]
            default_model = (
                base.model if base.model in options and provider_name == base.provider else model
            )
            model = st.selectbox(
                "Model",
                options,
                index=options.index(default_model) if default_model in options else 0,
                format_func=lambda m: (
                    f"{get_model_info(m).display_name} (${get_model_info(m).input_per_mtok:g} / "
                    f"${get_model_info(m).output_per_mtok:g} per 1M tokens)"
                ),
            )
        with st.expander("Answer settings"):
            prompt_version = st.radio(
                "Question-answering prompt",
                ["v2", "v1"],
                horizontal=True,
                index=0 if base.qa_prompt_version == "v2" else 1,
                help="v2 is the revised prompt (default). v1 is the original baseline, kept for comparison.",
            )
            retriever = st.selectbox(
                "Search method",
                ["hybrid", "bm25", "char_ngram"],
                index=["hybrid", "bm25", "char_ngram"].index(base.retriever),
                format_func={
                    "hybrid": "Hybrid (default)",
                    "bm25": "Keyword (BM25)",
                    "char_ngram": "Character n-grams",
                }.get,
            )
            top_k = st.slider("Passages per answer", 3, 12, base.top_k)
        settings = base.with_overrides(
            provider=provider_name,
            model=None if provider_name == "mock" else model,
            qa_prompt_version=prompt_version,
            retriever=retriever,
            top_k=top_k,
        )
        ws.settings = settings
        provider, fallback_reason = get_provider(settings)

        if provider.is_offline:
            st.info(
                "Offline demo mode: answers are sentences copied from your documents by a simple "
                "keyword method, not written by an AI model."
                + (f" ({fallback_reason})" if fallback_reason else "")
                + (
                    ""
                    if len(available) > 1
                    else " To use a hosted model, add an API key to your .env file "
                    "(see .env.example) and restart."
                ),
                icon=":material/cloud_off:",
            )

        st.divider()
        # ---- documents
        st.markdown("#### Documents")
        uploads = st.file_uploader(
            "Add PDFs",
            type=["pdf"],
            accept_multiple_files=True,
            key=f"uploader_{st.session_state.uploader_key}",
            max_upload_size=int(settings.max_file_mb),
            help=f"Up to {settings.max_documents} files, {settings.max_file_mb:g} MB and "
            f"{settings.max_pages_per_document} pages each. Scanned PDFs need OCR first.",
        )
        for upload in uploads or []:
            ident = getattr(upload, "file_id", None) or (upload.name, upload.size)
            if ident in st.session_state.processed_uploads:
                continue
            st.session_state.processed_uploads.add(ident)
            with st.spinner(f"Reading {upload.name}…"):
                result = ws.add_pdf(upload.name, upload.getvalue())
            if result.error:
                st.session_state.upload_messages.append(("error", result.error))
            elif result.duplicate:
                st.session_state.upload_messages.append(
                    ("info", f"'{result.filename}' is already loaded.")
                )
            else:
                st.session_state.upload_messages.append(
                    ("success", f"Added '{result.filename}' ({result.record.page_count} pages).")
                )
        if st.button(
            "Load sample documents",
            icon=":material/library_add:",
            width="stretch",
            help="Seven short synthetic documents (contract, amendment, reports, policy, a "
            "research brief and a proposal containing a prompt-injection attempt).",
        ):
            load_samples()
        for kind, message in st.session_state.upload_messages[-4:]:
            {"error": st.error, "info": st.info, "success": st.success}[kind](message)
        st.session_state.upload_messages = st.session_state.upload_messages[-4:]

        for record in ws.documents:
            loaded = ws.get(record.doc_id)
            with st.container(border=True):
                st.markdown(f"**{md(record.filename)}**")
                st.caption(
                    f"{record.page_count} pages, {len(loaded.chunks)} passages",
                    help=" ".join(record.notes) or None,
                )
                for warning in record.warnings:
                    st.warning(warning, icon=":material/warning:")
                if loaded.flagged_chunks:
                    pages = sorted(
                        {c.page_number for c in loaded.chunks if "instruction_like_text" in c.flags}
                    )
                    st.warning(
                        f"Contains text that looks like instructions to an AI (page {', '.join(map(str, pages))}). "
                        "It is treated as document content only.",
                        icon=":material/shield:",
                    )
                if st.button("Remove", key=f"remove_{record.doc_id}", icon=":material/delete:"):
                    ws.remove(record.doc_id)
                    st.rerun()

        if ws.documents:
            stats = ws.stats()
            st.caption(
                f"{stats['documents']} documents, {stats['pages']} pages, {stats['chunks']} searchable passages."
            )
            with st.popover("Clear session", icon=":material/restart_alt:", width="stretch"):
                st.write("Remove all documents, answers and ratings from this session?")
                if st.button("Clear everything", type="primary"):
                    clear_session()
                    st.rerun()

        st.divider()
        with st.expander("How your data is handled"):
            provider_label = PROVIDER_LABELS.get(provider.provider_name, "the selected provider")
            st.markdown(
                md(
                    f"- Files are processed in this browser session's memory only and are discarded when you "
                    f"clear the session or close the tab. Nothing is written to disk or shared with other users.\n"
                    f"- With a hosted model, your question and the retrieved passages (for summaries and "
                    f"extraction: the selected documents' text) are sent to **{provider_label}**. "
                    "OpenAI requests are sent with storage disabled (`store=false`).\n"
                    "- Do not upload confidential documents unless your organization allows them to be "
                    "processed by this provider.\n"
                    "- Logs record events and counts only, never document text or questions."
                )
            )
    return settings, provider, fallback_reason


# --------------------------------------------------------------------------- page preview


@st.dialog("Cited page", width="large")
def page_dialog(doc_id: str, page_number: int, quotes: tuple[str, ...]) -> None:
    ws: DocumentWorkspace = st.session_state.workspace
    loaded = ws.get(doc_id)
    if loaded is None:
        st.warning("This document is no longer loaded.")
        return
    key = (doc_id, page_number, quotes)
    cache: dict = st.session_state.page_cache
    if key not in cache:
        if len(cache) > 24:
            cache.clear()
        cache[key] = render_page_png(loaded.data, page_number, list(quotes))
    st.caption(
        f"{loaded.record.filename}, page {page_number} of {loaded.record.page_count}. "
        "Cited text is highlighted where it could be located on the page."
    )
    if cache[key]:
        st.image(
            cache[key],
            width="stretch",
            alt=f"Page {page_number} of {loaded.record.filename} with the cited text highlighted",
        )
    else:
        st.warning("This page could not be rendered.")


# --------------------------------------------------------------------------- evidence rendering


def render_grounding(report: GroundingReport) -> None:
    label, color = VERDICT_BADGES[report.verdict]
    st.badge(label, color=color, help=CHECK_HELP)
    st.caption(report.summary_line())
    for warning in report.warnings:
        st.warning(md(warning), icon=":material/warning:")


def render_source(passage: SourcePassage, checks: list[CitationCheck], key_prefix: str) -> None:
    quotes = [c.quote for c in checks if c.quote]
    with st.container(border=True):
        st.html(
            f'<div style="overflow-wrap:anywhere">{chip_html(passage.source_id)} '
            f"<strong>{html.escape(passage.filename)}</strong>"
            f'<span class="di-meta">, page {passage.page_number}</span></div>'
        )
        statuses = {c.quote_status for c in checks if c.quote_status in QUOTE_BADGES}
        for status in sorted(statuses):
            label, color = QUOTE_BADGES[status]
            st.badge(label, color=color)
        if "instruction_like_text" in passage.flags:
            st.badge("Contains instruction-like text", color="orange", icon=":material/shield:")
        st.html(highlight_html(passage.text, quotes))
        notes = sorted({n for c in checks for n in c.notes})
        for note in notes:
            st.caption(md(note))
        if st.button(
            f"View page {passage.page_number}",
            key=f"{key_prefix}_{passage.source_id}",
            icon=":material/visibility:",
        ):
            page_dialog(passage.doc_id, passage.page_number, tuple(quotes))


def render_evidence(result: QAResult, turn_id: int) -> None:
    st.markdown("#### Evidence")
    render_grounding(result.report)
    cited_ids = {c.source_id for c in result.report.checks if c.known}
    by_source: dict[str, list[CitationCheck]] = {}
    for check in result.report.checks:
        by_source.setdefault(check.source_id, []).append(check)
    unknown = [c for c in result.report.checks if not c.known]
    if unknown:
        st.error(
            "The answer cites "
            + ", ".join(sorted({c.source_id for c in unknown}))
            + ", which was never provided to the model. Treat those statements as unsupported.",
            icon=":material/report:",
        )
    for p in result.sources:
        if p.source_id in cited_ids:
            render_source(p, by_source.get(p.source_id, []), f"src_{turn_id}")
    uncited = [p for p in result.sources if p.source_id not in cited_ids]
    if uncited:
        with st.expander(f"Other retrieved passages ({len(uncited)}, not cited)"):
            for p in uncited:
                render_source(p, [], f"unc_{turn_id}")
    with st.expander("Diagnostics"):
        r = result.retrieval
        st.caption(
            md(
                f"Prompt {result.prompt_label}; search method {r.retriever}; {r.candidates} candidate passages; "
                f"{len(result.sources)} sent to the model (~{r.estimated_context_tokens:,} of {r.token_budget:,} "
                f"tokens); duplicates skipped {r.skipped_duplicates}; over budget {r.skipped_for_budget}."
                + (
                    " The previous question was added to the search for this follow-up."
                    if r.used_history_for_retrieval
                    else ""
                )
            )
        )
        st.caption(md(stats_caption(result.stats)))
        for note in r.notes:
            st.caption(md(note))


# --------------------------------------------------------------------------- tabs


def _queue_example() -> None:
    """Callback: run the clicked example question on this rerun, then reset the pills."""
    picked = st.session_state.get("example_pills")
    if picked:
        st.session_state.pending_question = picked
    st.session_state.example_pills = None


def ask_tab(provider: LLMProvider) -> None:
    ws: DocumentWorkspace = st.session_state.workspace
    left, right = st.columns([0.56, 0.44], gap="large")
    with left:
        history_box = st.container()
        scope_names = {r.doc_id: r.filename for r in ws.documents}
        scope = list(scope_names)
        if len(scope_names) > 1:
            chosen = [d for d in st.session_state.get("ask_scope", scope) if d in scope_names]
            label = (
                "Searching all documents"
                if len(chosen) == len(scope_names)
                else f"Searching {len(chosen)} of {len(scope_names)} documents"
            )
            with st.expander(label, icon=":material/filter_list:"):
                scope = st.multiselect(
                    "Documents to search",
                    list(scope_names),
                    default=list(scope_names),
                    format_func=scope_names.get,
                    key="ask_scope",
                )
        question = st.chat_input(
            "Ask about your documents…",
            max_chars=ws.settings.max_question_chars,
            disabled=not ws.documents,
        )
        if not question and st.session_state.pending_question:
            question = st.session_state.pending_question
        st.session_state.pending_question = None

        if question:
            history = [
                ConversationTurn(m["question"], m["result"].output.answer)
                for m in st.session_state.messages
                if m.get("result")
            ][-ws.settings.history_turns :]
            st.session_state.turn_counter += 1
            turn = {
                "id": st.session_state.turn_counter,
                "question": question,
                "result": None,
                "error": None,
            }
            with st.spinner("Searching your documents and drafting a grounded answer…"):
                try:
                    turn["result"] = answer_question(
                        ws, provider, question, history=history, doc_ids=scope
                    )
                except Exception as exc:
                    turn["error"] = exc
            st.session_state.messages.append(turn)
            st.session_state.selected_turn = turn["id"]

        with history_box:
            if not st.session_state.messages:
                if ws.documents:
                    st.markdown(
                        "Ask a question in your own words. Answers cite the passages they rely on."
                    )
                    if any(r.filename in SAMPLE_FILES for r in ws.documents):
                        st.pills(
                            "Try one of these",
                            EXAMPLE_QUESTIONS,
                            key="example_pills",
                            on_change=_queue_example,
                        )
                else:
                    st.info(
                        "Add PDFs in the sidebar, or load the sample documents to try every feature.",
                        icon=":material/upload_file:",
                    )
            for turn in st.session_state.messages:
                with st.chat_message("user", avatar=":material/person:"):
                    st.markdown(md(turn["question"]))
                with st.chat_message("assistant", avatar=":material/find_in_page:"):
                    if turn["error"] is not None:
                        show_error(turn["error"])
                        continue
                    result: QAResult = turn["result"]
                    label, color = STATUS_BADGES[result.output.status]
                    st.badge(label, color=color)
                    if result.offline:
                        st.badge("Offline extractive baseline", color="gray")
                    st.html(answer_html(result.output.answer))
                    if result.output.conflicts:
                        for conflict in result.output.conflicts:
                            nature, _ = NATURE_LABELS.get(conflict.nature, ("Unclear", "orange"))
                            st.html(
                                f"<div class='di-answer'><strong>{html.escape(nature)}:</strong> "
                                f"{html.escape(conflict.description)} "
                                + "".join(chip_html(s) for s in conflict.source_ids)
                                + "</div>"
                            )
                    if result.output.missing_information:
                        st.caption(
                            md(
                                "Not covered by the documents: "
                                + "; ".join(result.output.missing_information)
                            )
                        )
                    inferences = [
                        c.statement for c in result.output.claims if c.claim_type == "inference"
                    ]
                    if inferences:
                        st.caption(
                            md(
                                "Inferences (reasoning, not stated directly): "
                                + " ".join(inferences)
                            )
                        )
                    st.caption(f"Confidence: {result.output.confidence}")
                    cols = st.columns([0.55, 0.45])
                    with cols[0]:
                        rating = st.feedback("thumbs", key=f"rating_{turn['id']}")
                        if rating is not None:
                            st.session_state.ratings[turn["id"]] = {
                                "question": turn["question"],
                                "useful": bool(rating),
                                "status": result.output.status,
                                "verdict": result.report.verdict,
                                "prompt": result.prompt_label,
                                "model": result.provider_label,
                            }
                    with cols[1]:
                        if st.session_state.selected_turn != turn["id"] and st.button(
                            "Show evidence", key=f"show_{turn['id']}", icon=":material/fact_check:"
                        ):
                            st.session_state.selected_turn = turn["id"]
                            st.rerun()

    with right:
        selected = next(
            (
                t
                for t in st.session_state.messages
                if t["id"] == st.session_state.selected_turn and t.get("result")
            ),
            None,
        )
        if selected:
            render_evidence(selected["result"], selected["id"])
        else:
            st.markdown("#### Evidence")
            st.caption(
                "The passages behind each answer appear here, with the quoted words highlighted."
            )


def doc_picker(label: str, key: str, *, minimum: int = 1, default_all: bool = False) -> list[str]:
    ws: DocumentWorkspace = st.session_state.workspace
    names = {r.doc_id: r.filename for r in ws.documents}
    default = list(names) if default_all else list(names)[:minimum]
    return st.multiselect(label, list(names), default=default, format_func=names.get, key=key)


def plan_caption(plan) -> str:
    cost = (
        "free (offline)"
        if plan.estimated_cost_usd == 0
        else (
            f"about ${plan.estimated_cost_usd:.4f}"
            if plan.estimated_cost_usd is not None
            else "cost unknown"
        )
    )
    text = f"Plan: {plan.calls} model call(s), roughly {plan.estimated_input_tokens:,} input tokens, {cost}."
    if plan.truncated:
        text += (
            " The selection is longer than one run covers; the result will list the pages left out."
        )
    return text


def points_block(title: str, points, sources_by_id: dict[str, SourcePassage]) -> None:
    if not points:
        return
    st.markdown(f"**{title}**")
    items = []
    for p in points:
        refs = "".join(chip_html(s) for s in p.source_ids)
        pages = sorted(
            {
                (sources_by_id[s].filename, sources_by_id[s].page_number)
                for s in p.source_ids
                if s in sources_by_id
            }
        )
        where = "; ".join(f"{html.escape(f)} p.{n}" for f, n in pages)
        items.append(f"<li>{html.escape(p.text)} {refs} <span class='di-meta'>{where}</span></li>")
    st.html(f"<div class='di-answer'><ul>{''.join(items)}</ul></div>")


def summarize_tab(provider: LLMProvider) -> None:
    ws: DocumentWorkspace = st.session_state.workspace
    if not ws.documents:
        st.info("Load documents first to summarize them.", icon=":material/upload_file:")
        return
    doc_ids = doc_picker("Documents to summarize", "sum_docs")
    focus = st.text_input(
        "Focus (optional)", placeholder="e.g. obligations and deadlines", key="sum_focus"
    )
    if doc_ids:
        try:
            st.caption(plan_caption(plan_summary(ws, provider, doc_ids)))
        except WorkflowError as exc:
            st.warning(exc.user_message)
    if st.button("Summarize", type="primary", disabled=not doc_ids, icon=":material/summarize:"):
        with st.spinner("Summarizing every section of the selected documents…"):
            try:
                st.session_state.summary_result = summarize_documents(
                    ws, provider, doc_ids, focus=focus
                )
            except Exception as exc:
                show_error(exc)
    result = st.session_state.summary_result
    if result is None:
        return
    sources = {p.source_id: p for p in result.sources}
    out = result.output
    st.divider()
    if result.offline:
        st.badge(
            "Offline extractive baseline: copied sentences, not a written summary", color="gray"
        )
    render_grounding(result.report)
    st.caption(md(result.coverage.summary_line() + f" Method: {result.method.replace('_', ' ')}."))
    st.markdown("### Executive summary")
    st.html(answer_html(out.executive_summary))
    with st.expander("Detailed summary", expanded=False):
        st.html(answer_html(out.detailed_summary))
    points_block("Key findings", out.key_findings, sources)
    if out.important_dates:
        st.markdown("**Important dates**")
        st.html(
            "<div class='di-answer'><ul>"
            + "".join(
                f"<li><strong>{html.escape(d.date)}</strong>: {html.escape(d.description)} "
                + "".join(chip_html(s) for s in d.source_ids)
                + "</li>"
                for d in out.important_dates
            )
            + "</ul></div>"
        )
    points_block("Action items", out.action_items, sources)
    points_block("Obligations", out.obligations, sources)
    points_block("Risks and concerns", out.risks_and_concerns, sources)
    if out.gaps_or_limitations:
        st.markdown("**Gaps and limitations**")
        for gap in out.gaps_or_limitations:
            st.caption(md(gap))
    st.caption(md(stats_caption(result.stats)))
    st.download_button(
        "Download summary (JSON)",
        json.dumps(out.model_dump(), indent=2),
        file_name="docintel_summary.json",
        mime="application/json",
        icon=":material/download:",
    )


def extract_tab(provider: LLMProvider) -> None:
    ws: DocumentWorkspace = st.session_state.workspace
    if not ws.documents:
        st.info("Load documents first to extract information.", icon=":material/upload_file:")
        return
    doc_ids = doc_picker("Documents", "ext_docs")
    categories = st.pills(
        "Information to extract",
        list(EXTRACTION_CATEGORIES),
        selection_mode="multi",
        default=list(EXTRACTION_CATEGORIES),
        format_func=CATEGORY_LABELS.get,
        key="ext_cats",
    )
    if doc_ids:
        try:
            st.caption(plan_caption(plan_extraction(ws, provider, doc_ids)))
        except WorkflowError as exc:
            st.warning(exc.user_message)
    if st.button(
        "Extract",
        type="primary",
        disabled=not doc_ids or not categories,
        icon=":material/table_view:",
    ):
        with st.spinner("Extracting structured information…"):
            try:
                st.session_state.extraction_result = extract_information(
                    ws, provider, doc_ids, categories
                )
            except Exception as exc:
                show_error(exc)
    result = st.session_state.extraction_result
    if result is None:
        return
    st.divider()
    if result.offline:
        st.badge("Offline extractive baseline: regular-expression matches", color="gray")
    render_grounding(result.report)
    sources = {p.source_id: p for p in result.sources}
    checks = {c.ref: c for c in result.report.checks}
    rows_all = []
    for category in result.categories:
        items = getattr(result.output, category)
        st.markdown(f"**{CATEGORY_LABELS[category]}**")
        if not items:
            st.caption("Not found in the selected documents.")
            continue
        rows = []
        for i, item in enumerate(items):
            src = sources.get(item.source_id)
            check = checks.get(f"{category}[{i}]")
            row = {
                "Value": item.value,
                "Detail": item.detail or "not stated",
                "Normalized": item.normalized_value or "",
                "Source": f"{item.source_id}: {src.filename} p.{src.page_number}"
                if src
                else f"{item.source_id} (unknown)",
                "Quote check": QUOTE_BADGES.get(check.quote_status, ("n/a", ""))[0]
                if check
                else "n/a",
                "Quote": item.quote,
            }
            rows.append(row)
            rows_all.append({"Category": CATEGORY_LABELS[category], **row})
        st.dataframe(rows, hide_index=True, width="stretch")
    if result.duplicates_removed:
        st.caption(
            f"{result.duplicates_removed} duplicate item(s) found in several sections were merged."
        )
    st.caption(md(result.coverage.summary_line() + " " + stats_caption(result.stats)))
    st.download_button(
        "Download extraction (JSON)",
        json.dumps(result.output.model_dump(), indent=2),
        file_name="docintel_extraction.json",
        mime="application/json",
        icon=":material/download:",
    )


def compare_tab(provider: LLMProvider) -> None:
    ws: DocumentWorkspace = st.session_state.workspace
    if len(ws.documents) < 2:
        st.info("Load at least two documents to compare them.", icon=":material/upload_file:")
        return
    names = {r.doc_id: r.filename for r in ws.documents}
    doc_ids = st.multiselect(
        "Documents to compare (2 to 4)",
        list(names),
        default=list(names)[:2],
        format_func=names.get,
        max_selections=4,
        key="cmp_docs",
    )
    focus = st.text_input(
        "Focus (optional)", placeholder="e.g. fees, deadlines and service levels", key="cmp_focus"
    )
    if st.button("Compare", type="primary", disabled=len(doc_ids) < 2, icon=":material/compare:"):
        with st.spinner("Comparing documents…"):
            try:
                st.session_state.comparison_result = compare_documents(
                    ws, provider, doc_ids, focus=focus
                )
            except Exception as exc:
                show_error(exc)
    result = st.session_state.comparison_result
    if result is None:
        return
    st.divider()
    if result.offline:
        st.badge("Offline extractive baseline: word-overlap alignment", color="gray")
    render_grounding(result.report)
    st.html(answer_html(result.output.overview))
    sources = {p.source_id: p for p in result.sources}
    by_category: dict[str, list] = {}
    for finding in result.output.findings:
        by_category.setdefault(finding.category, []).append(finding)
    for category, title in CATEGORY_TITLES.items():
        findings = by_category.get(category)
        if not findings:
            continue
        st.markdown(f"**{title}**")
        for f in findings:
            nature, color = NATURE_LABELS[f.nature]
            with st.container(border=True):
                st.markdown(f"**{md(f.topic)}**")
                if category in {
                    "conflict",
                    "numerical_discrepancy",
                    "important_change",
                    "difference",
                    "obligation_or_deadline_difference",
                }:
                    st.badge(nature, color=color)
                st.html(answer_html(f.description))
                where = sorted(
                    {
                        f"{sources[s].filename} p.{sources[s].page_number}"
                        for s in f.source_ids
                        if s in sources
                    }
                )
                st.caption(
                    md("Sources: " + "; ".join(where)) if where else "No valid sources cited."
                )
    if not result.output.findings:
        st.caption("No findings were returned.")
    if result.output.limitations:
        st.caption(md("Limitations: " + result.output.limitations))
    st.caption(md(result.coverage.summary_line() + " " + stats_caption(result.stats)))


def evaluation_tab() -> None:
    st.markdown("### Your ratings in this session")
    ratings = st.session_state.ratings
    if ratings:
        useful = sum(1 for r in ratings.values() if r["useful"])
        st.write(f"{useful} of {len(ratings)} rated answers marked useful.")
        st.dataframe(list(ratings.values()), hide_index=True, width="stretch")
        st.download_button(
            "Download ratings (JSON)",
            json.dumps(list(ratings.values()), indent=2),
            file_name="docintel_ratings.json",
            mime="application/json",
            icon=":material/download:",
        )
    else:
        st.caption(
            "Rate answers with the thumbs buttons in the Ask tab. Ratings stay in this session "
            "until you download them."
        )
    st.markdown("### Saved evaluation runs")
    results_dir = ROOT / "evaluation" / "results"
    runs = sorted(results_dir.glob("*.json")) if results_dir.is_dir() else []
    e2e, retrieval = [], []
    for path in runs:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        (retrieval if "per_case" in data else e2e).append((path, data))
    if not e2e:
        st.caption(
            "No evaluation runs have been saved yet. Run `python -m evaluation.evaluation_runner`."
        )
    rows = []
    for _path, data in e2e:
        meta, m = data["metadata"], data["metrics"]
        rows.append(
            {
                "Run": meta["run_id"],
                "Model": f"{meta['provider']}:{meta['model']}",
                "Offline baseline": meta["offline"],
                "Prompt": meta["prompt_version"],
                "Cases": meta["case_count"],
                "Pass rate": m["overall_pass_rate"],
                "Answer accuracy": m["answer_accuracy"],
                "Correct abstention": m["correct_abstention_rate"],
                "Injection resistance": m["injection_resistance_rate"],
                "Quote match": m["quote_match_rate"],
                "Cost (USD)": m["cost_usd"],
            }
        )
    if rows:
        st.dataframe(rows, hide_index=True, width="stretch")
        if all(r["Offline baseline"] for r in rows):
            st.caption(
                "Only the offline extractive baseline has been evaluated so far. Live model results "
                "are pending an API key and approval to spend on API calls."
            )
    if retrieval:
        path, data = retrieval[-1]
        st.markdown("### Retrieval benchmark")
        table = []
        for set_name, by_retriever in data["results"].items():
            for name, metrics in by_retriever.items():
                table.append({"Question set": set_name, "Search method": name, **metrics})
        st.dataframe(table, hide_index=True, width="stretch")
        st.caption(f"From {path.name}. See docs/EVALUATION_REPORT.md for interpretation.")


def about_tab(settings: Settings, provider: LLMProvider) -> None:
    st.markdown("### How DocIntel answers")
    st.graphviz_chart(
        """
        digraph G {
          rankdir=LR; bgcolor="transparent";
          node [shape=box, style="rounded,filled", fillcolor="#F3F5F9", color="#C9D2E3", fontname="Helvetica", fontsize=11];
          edge [color="#7A879C"];
          pdf [label="PDF upload\\n(validated)"]; extract [label="Text + page\\nextraction"];
          chunk [label="Page-aware\\nchunks"]; search [label="Hybrid search\\n(BM25 + n-grams)"];
          prompt [label="Versioned prompt\\n(sources as data)"]; llm [label="LLM with JSON\\nschema output"];
          check [label="Citation checks\\n(IDs, quotes, support)"]; ui [label="Answer +\\nhighlighted evidence"];
          pdf -> extract -> chunk -> search -> prompt -> llm -> check -> ui;
        }
        """,
        width="stretch",
    )
    info = get_model_info(provider.model)
    st.markdown(
        md(
            f"**Current model:** {PROVIDER_LABELS.get(settings.provider, settings.provider)} "
            f"`{provider.model}`"
            + (" (offline baseline, no API calls)" if provider.is_offline else "")
            + (
                f", priced at ${info.input_per_mtok:g} input / ${info.output_per_mtok:g} output per million "
                f"tokens (prices checked {VERIFIED_ON})."
                if info
                else "."
            )
        )
    )
    st.markdown(
        md(
            "1. **Extraction.** PyMuPDF reads each page's text in memory. Running headers and footers that repeat on "
            "most pages are removed (and reported). Scanned pages without a text layer are flagged, because OCR is not "
            "performed.\n"
            "2. **Retrieval.** Pages are split into overlapping passages that never cross a page boundary. A hybrid of "
            "keyword (BM25) and character n-gram search finds the passages most related to the question.\n"
            "3. **Prompting.** The model receives versioned system instructions, the question, and the passages as "
            "labelled, untrusted `<source>` blocks with IDs (S1, S2, ...). Text inside documents is data, never "
            "instructions.\n"
            "4. **Structured output.** The model must return JSON matching a schema: status, answer, claims with "
            "verbatim quotes, conflicts and missing information.\n"
            "5. **Verification.** Every citation is checked: the ID must have been provided, the quote must appear in "
            "that passage, and a heuristic checks that the claim's terms and numbers occur in it.\n"
            "6. **Human review.** You read the highlighted evidence and decide."
        )
    )
    st.markdown("### Limitations")
    st.markdown(
        md(
            "- Answers can still be wrong or incomplete, even with valid citations.\n"
            '- Keyword-based search can miss passages that use very different wording (for example "drinks" '
            'versus "alcoholic beverages").\n'
            "- No OCR: scanned pages without a text layer cannot be searched. Tables and multi-column layouts may "
            "extract imperfectly.\n"
            "- The support check is a heuristic, not proof. The prompt-injection filter is a warning system, not a "
            "guarantee.\n"
            "- This is an academic prototype for AAI-530. It is not a substitute for professional legal, financial or "
            "medical advice."
        )
    )
    st.markdown("### About this project")
    st.markdown(
        md(
            "Built for AAI-530 (Large Language Model Engineering) by Robert, Josue and Marie. Implementation was "
            "assisted by Claude Code and planning/review by ChatGPT; see `docs/AI_USE_AND_ETHICAL_REFLECTION.md`. "
            "All sample documents are synthetic."
        )
    )


# --------------------------------------------------------------------------- main


def main() -> None:
    init_state()
    st.markdown(STYLE, unsafe_allow_html=True)
    settings, provider, _ = sidebar()

    st.title(PRODUCT_NAME)
    st.markdown(
        '<p class="di-subtitle">Ask questions about your PDFs and see the exact passages behind '
        "every answer.</p>",
        unsafe_allow_html=True,
    )
    st.caption(
        "AI answers can be wrong. Check the highlighted sources before you rely on them, especially "
        "for legal, financial or medical decisions."
    )

    tabs = st.tabs(["Ask", "Summarize", "Extract", "Compare", "Evaluation", "About"])
    with tabs[0]:
        ask_tab(provider)
    with tabs[1]:
        summarize_tab(provider)
    with tabs[2]:
        extract_tab(provider)
    with tabs[3]:
        compare_tab(provider)
    with tabs[4]:
        evaluation_tab()
    with tabs[5]:
        about_tab(settings, provider)


main()
