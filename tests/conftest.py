"""Shared test fixtures. All tests run offline: no API keys, no network, no paid calls."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import pymupdf
import pytest

from docintel import config
from docintel.config import FIXTURES_DIR, Settings
from docintel.models import DocumentRecord, PageText, SourcePassage
from docintel.session import DocumentWorkspace

API_KEY_VARS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY")
# Everything the installed provider SDKs read from the environment that affects where requests go,
# which credentials or headers they carry, or what gets logged.
PROVIDER_SDK_ENV_VARS = (
    *API_KEY_VARS,
    "OPENAI_ADMIN_KEY",
    "OPENAI_ORG_ID",
    "OPENAI_PROJECT_ID",
    "OPENAI_BASE_URL",
    "OPENAI_CUSTOM_HEADERS",
    "OPENAI_LOG",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_CUSTOM_HEADERS",
    "ANTHROPIC_LOG",
    "ANTHROPIC_PROFILE",
    "ANTHROPIC_CONFIG_DIR",
    "ANTHROPIC_OPEN_TELEMETRY_TRACES_CONTENT_MODE",
    "GOOGLE_GENAI_USE_VERTEXAI",
    "GOOGLE_GENAI_USE_ENTERPRISE",
)


@pytest.fixture(autouse=True)
def _no_real_api_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Guarantee tests never pick up a developer's real API keys or settings.

    Removing the variables is not enough: ``Settings.from_env()`` (called by app.py in the UI
    tests) also reads ``.env``, and a real key there would let tests in owner mode call a paid
    API. Reading ``.env`` is therefore disabled, and ``DOCINTEL_*`` and provider SDK variables
    from the shell are removed.
    """
    for var in PROVIDER_SDK_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    for var in [name for name in os.environ if name.startswith("DOCINTEL_")]:
        monkeypatch.delenv(var)
    monkeypatch.setattr(config, "_dotenv_values", dict)


@pytest.fixture
def settings() -> Settings:
    return Settings(provider="mock")


@pytest.fixture
def make_pdf() -> Callable[..., bytes]:
    """Build a simple text PDF in memory: one string per page."""

    def _make(
        pages: list[str],
        *,
        title: str = "",
        encrypt_user_pw: str | None = None,
        owner_only: bool = False,
    ) -> bytes:
        doc = pymupdf.open()
        for text in pages:
            page = doc.new_page()
            if text:
                page.insert_textbox(pymupdf.Rect(72, 72, 540, 760), text, fontsize=11)
        if title:
            doc.set_metadata({"title": title})
        if encrypt_user_pw is not None or owner_only:
            data = doc.tobytes(
                encryption=pymupdf.PDF_ENCRYPT_AES_256,
                owner_pw="owner-secret",
                user_pw="" if owner_only else encrypt_user_pw,
            )
        else:
            data = doc.tobytes()
        doc.close()
        return data

    return _make


@pytest.fixture
def fixture_bytes() -> Callable[[str], bytes]:
    def _read(name: str) -> bytes:
        return (FIXTURES_DIR / name).read_bytes()

    return _read


@pytest.fixture
def workspace_with(settings: Settings, fixture_bytes) -> Callable[..., DocumentWorkspace]:
    def _build(*names: str, settings_override: Settings | None = None) -> DocumentWorkspace:
        ws = DocumentWorkspace(settings_override or settings)
        for name in names:
            result = ws.add_pdf(name, fixture_bytes(name))
            assert result.ok, result.error
        return ws

    return _build


def make_record(
    pages: list[str], doc_id: str = "doc-test000001", filename: str = "test.pdf", title: str = ""
) -> DocumentRecord:
    return DocumentRecord(
        doc_id=doc_id,
        filename=filename,
        sha256="0" * 64,
        size_bytes=1,
        page_count=len(pages),
        pages=[PageText(page_number=i + 1, text=t) for i, t in enumerate(pages)],
        metadata={"title": title} if title else {},
    )


def passage(
    source_id: str,
    text: str,
    *,
    doc_id: str = "doc-a",
    filename: str = "a.pdf",
    page: int = 1,
    flags: list[str] | None = None,
) -> SourcePassage:
    return SourcePassage(
        source_id=source_id,
        chunk_id=f"{doc_id}:p{page}:c0",
        doc_id=doc_id,
        filename=filename,
        page_number=page,
        text=text,
        flags=flags or [],
    )


MSA = "larkspur_master_services_agreement.pdf"
AMENDMENT = "larkspur_amendment_no1.pdf"
STATUS = "catalog_project_status_q3_2026.pdf"
MEMO = "catalog_finance_memo_oct_2026.pdf"
RESEARCH = "urban_heat_research_brief.pdf"
POLICY = "staff_travel_policy.pdf"
BRIGHTLINE = "brightline_vendor_proposal.pdf"
SCANNED = "scanned_notice_image_only.pdf"
ROOT = Path(__file__).resolve().parents[1]
