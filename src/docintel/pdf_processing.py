"""PDF validation and text extraction with PyMuPDF.

Files are processed entirely in memory (``pymupdf.open(stream=...)``): no temporary files are
written, so there is nothing to clean up on disk. Pages are numbered from 1, matching what a
PDF viewer shows. Content is never silently discarded: pages that yield no text are recorded
in ``DocumentRecord.empty_pages`` and surfaced as warnings.
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

import pymupdf

from docintel.config import Settings
from docintel.models import DocumentRecord, PageText
from docintel.security import get_logger, sanitize_filename, sanitize_inline

PDF_MAGIC = b"%PDF-"
log = get_logger("pdf")


@dataclass
class PDFValidationError(Exception):
    """A user-correctable problem with an uploaded file."""

    code: str  # too_large | not_pdf | corrupt | encrypted | empty | too_many_pages | no_text
    user_message: str

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.code}: {self.user_message}"


def compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_doc_id(sha256: str) -> str:
    return f"doc-{sha256[:10]}"


def validate_upload(filename: str, data: bytes, settings: Settings) -> None:
    """Cheap checks that run before the PDF parser touches the bytes."""
    if not data:
        raise PDFValidationError("empty", f"'{filename}' is empty (0 bytes).")
    if len(data) > settings.max_file_bytes:
        size_mb = len(data) / (1024 * 1024)
        raise PDFValidationError(
            "too_large",
            f"'{filename}' is {size_mb:.1f} MB; the limit is {settings.max_file_mb:g} MB.",
        )
    if not filename.lower().endswith(".pdf"):
        raise PDFValidationError("not_pdf", f"'{filename}' does not have a .pdf extension.")
    # The PDF header must appear near the start of the file (spec allows a small preamble).
    if PDF_MAGIC not in data[:1024]:
        raise PDFValidationError(
            "not_pdf", f"'{filename}' is not a valid PDF file (missing PDF header)."
        )


# --------------------------------------------------------------------------- text normalization

_SOFT_HYPHEN = "­"
_SPACE_VARIANTS = re.compile(r"[  -   　\t\f\v]")
_ZERO_WIDTH = re.compile(r"[​‌‍⁠﻿]")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0e-\x1f\x7f]")
_LINE_HYPHEN_WORD = re.compile(r"([A-Za-z]+)-\n\s*([a-z]+)")
_WORD = re.compile(r"[A-Za-z]+")
_MULTI_SPACE = re.compile(r"[ ]{2,}")


def build_vocabulary(raw_blocks: list[str]) -> set[str]:
    """Lower-cased words of a document, excluding fragments split by a line-end hyphen."""
    vocabulary: set[str] = set()
    for text in raw_blocks:
        vocabulary.update(w.lower() for w in _WORD.findall(_LINE_HYPHEN_WORD.sub(" ", text)))
    return vocabulary


def normalize_block_text(text: str, vocabulary: set[str] | None = None) -> str:
    """Normalize one extracted text block into a single clean paragraph.

    A word broken by a hyphen at a line end ("infor-\nmation") is joined only when the joined
    word appears elsewhere in the document (``vocabulary``); otherwise the hyphen is kept, so
    genuine compounds such as "cross-\nsectional" or "go-\nlive" are not corrupted.
    """
    text = unicodedata.normalize("NFKC", text)  # also expands ligatures such as "ﬁ"
    text = text.replace(_SOFT_HYPHEN, "")
    text = _ZERO_WIDTH.sub("", text)
    text = _SPACE_VARIANTS.sub(" ", text)
    text = _CONTROL.sub(" ", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    def _rejoin(match: re.Match[str]) -> str:
        left, right = match.group(1), match.group(2)
        if vocabulary is not None and (left + right).lower() in vocabulary:
            return left + right
        return f"{left}-{right}"

    text = _LINE_HYPHEN_WORD.sub(_rejoin, text)
    text = re.sub(r"\s*\n\s*", " ", text)
    text = _MULTI_SPACE.sub(" ", text)
    return text.strip()


def extract_raw_blocks(page: pymupdf.Page) -> list[str]:
    """Raw text of the page's text blocks (images skipped), in reading order."""
    # block = (x0, y0, x1, y1, text, block_no, block_type); type 0 = text, 1 = image
    return [b[4] for b in page.get_text("blocks", sort=True) if len(b) < 7 or b[6] == 0]


def blocks_to_paragraphs(blocks: list[str], vocabulary: set[str] | None = None) -> list[str]:
    return [p for p in (normalize_block_text(b, vocabulary) for b in blocks) if p]


def extract_page_paragraphs(page: pymupdf.Page, vocabulary: set[str] | None = None) -> list[str]:
    """Return the page's text blocks as clean paragraphs, in reading order."""
    return blocks_to_paragraphs(extract_raw_blocks(page), vocabulary)


def extract_page_text(page: pymupdf.Page) -> str:
    """Return page text as paragraphs separated by blank lines, in reading order."""
    return "\n\n".join(extract_page_paragraphs(page))


def _boilerplate_key(paragraph: str) -> str:
    return re.sub(r"\d+", "#", paragraph.lower()).strip()


def strip_repeated_boilerplate(pages: list[list[str]]) -> tuple[list[list[str]], list[str]]:
    """Remove running headers/footers: paragraphs at the top or bottom of a page (first/last two
    blocks) that repeat, ignoring digits (e.g. "Page 3 of 9"), on at least 60% of the pages.

    Returns the cleaned pages and the distinct removed paragraphs (reported to the user, so the
    removal is never silent). Documents with fewer than 2 pages are left unchanged.
    """
    if len(pages) < 2:
        return pages, []
    counts: Counter[str] = Counter()
    for paragraphs in pages:
        counts.update({_boilerplate_key(p) for p in paragraphs[:2] + paragraphs[-2:]})
    threshold = max(2, math.ceil(0.6 * len(pages)))
    repeated = {k for k, c in counts.items() if c >= threshold and len(k) <= 300}
    if not repeated:
        return pages, []
    cleaned: list[list[str]] = []
    removed: list[str] = []
    for paragraphs in pages:
        keep = []
        for i, paragraph in enumerate(paragraphs):
            at_edge = i < 2 or i >= len(paragraphs) - 2
            if at_edge and _boilerplate_key(paragraph) in repeated:
                if _boilerplate_key(paragraph) not in {_boilerplate_key(r) for r in removed}:
                    removed.append(paragraph)
                continue
            keep.append(paragraph)
        cleaned.append(keep)
    return cleaned, removed


# --------------------------------------------------------------------------- extraction


def _open_pdf(filename: str, data: bytes) -> pymupdf.Document:
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except (pymupdf.FileDataError, pymupdf.EmptyFileError, RuntimeError, ValueError) as exc:
        log.info("pdf_open_failed error_type=%s", type(exc).__name__)
        raise PDFValidationError(
            "corrupt",
            f"'{filename}' could not be opened. The file may be corrupted or not a real PDF.",
        ) from None
    if not doc.is_pdf:
        doc.close()
        raise PDFValidationError("not_pdf", f"'{filename}' is not a PDF document.")
    return doc


def extract_document(filename: str, data: bytes, settings: Settings) -> DocumentRecord:
    """Validate and extract a PDF into a :class:`DocumentRecord`.

    Raises :class:`PDFValidationError` with a user-friendly message for files that cannot be used.
    """
    safe_name = sanitize_filename(filename)
    validate_upload(safe_name, data, settings)
    sha = compute_sha256(data)
    doc = _open_pdf(safe_name, data)
    try:
        if doc.needs_pass:
            raise PDFValidationError(
                "encrypted",
                f"'{safe_name}' is password-protected. Remove the password (e.g. re-export or "
                "print to PDF) and upload it again. DocIntel does not ask for document passwords.",
            )
        if doc.page_count == 0:
            raise PDFValidationError("empty", f"'{safe_name}' contains no pages.")
        if doc.page_count > settings.max_pages_per_document:
            raise PDFValidationError(
                "too_many_pages",
                f"'{safe_name}' has {doc.page_count} pages; the limit is "
                f"{settings.max_pages_per_document} pages per document.",
            )

        page_blocks: list[list[str]] = []
        page_images: list[bool] = []
        warnings: list[str] = []
        notes: list[str] = []
        failed_pages: list[int] = []
        for index in range(doc.page_count):
            page_number = index + 1
            try:
                page = doc.load_page(index)
                blocks = extract_raw_blocks(page)
                has_images = bool(page.get_images(full=False))
            except Exception as exc:
                log.warning(
                    "page_extract_failed page=%d error_type=%s", page_number, type(exc).__name__
                )
                blocks, has_images = [], False
                failed_pages.append(page_number)
            page_blocks.append(blocks)
            page_images.append(has_images)

        vocabulary = build_vocabulary([b for blocks in page_blocks for b in blocks])
        page_paragraphs = [blocks_to_paragraphs(blocks, vocabulary) for blocks in page_blocks]

        page_paragraphs, removed = strip_repeated_boilerplate(page_paragraphs)
        if removed:
            examples = "; ".join(f"'{sanitize_inline(r, 70)}'" for r in removed[:3])
            notes.append(
                f"Removed {len(removed)} running header/footer text(s) repeated on most pages: {examples}. "
                "They remain visible in the page images."
            )
        pages = [
            PageText(page_number=i + 1, text="\n\n".join(paragraphs), has_images=page_images[i])
            for i, paragraphs in enumerate(page_paragraphs)
        ]

        empty_pages = [p.page_number for p in pages if not p.text.strip()]
        if len(empty_pages) == len(pages):
            scanned = any(p.has_images for p in pages)
            hint = (
                " It appears to contain scanned images only. DocIntel does not perform OCR; run "
                "the file through an OCR tool first (e.g. 'Make searchable' in a PDF editor)."
                if scanned
                else ""
            )
            raise PDFValidationError("no_text", f"'{safe_name}' has no extractable text.{hint}")

        if failed_pages:
            warnings.append(
                "Text extraction failed on page(s) "
                + _format_pages(failed_pages)
                + "; they are excluded."
            )
        silent_empty = [p for p in empty_pages if p not in failed_pages]
        if silent_empty:
            image_pages = [p for p in silent_empty if pages[p - 1].has_images]
            warnings.append(
                "No extractable text on page(s) "
                + _format_pages(silent_empty)
                + (" (these pages contain images and may be scanned)" if image_pages else "")
                + ". Questions about those pages cannot be answered."
            )

        metadata = {
            key: sanitize_inline(str(value), max_len=200)
            for key, value in (doc.metadata or {}).items()
            if key in {"title", "author", "subject", "creationDate", "producer"} and value
        }
    finally:
        doc.close()

    record = DocumentRecord(
        doc_id=make_doc_id(sha),
        filename=safe_name,
        sha256=sha,
        size_bytes=len(data),
        page_count=len(pages),
        pages=pages,
        metadata=metadata,
        warnings=warnings,
        notes=notes,
        empty_pages=empty_pages,
    )
    log.info(
        "document_extracted doc_id=%s pages=%d empty_pages=%d chars=%d",
        record.doc_id,
        record.page_count,
        len(empty_pages),
        record.char_count,
    )
    return record


def _format_pages(pages: list[int]) -> str:
    """Compact page list: [1,2,3,7] -> '1-3, 7'."""
    if not pages:
        return ""
    ranges: list[str] = []
    start = prev = pages[0]
    for p in pages[1:]:
        if p == prev + 1:
            prev = p
            continue
        ranges.append(f"{start}-{prev}" if start != prev else str(start))
        start = prev = p
    ranges.append(f"{start}-{prev}" if start != prev else str(start))
    return ", ".join(ranges)


# Explicit search flags: expand ligatures ("ﬀ" -> "ff") so quotes taken from our NFKC-normalized
# text can be found in the PDF's raw text layer.
_SEARCH_FLAGS = pymupdf.TEXTFLAGS_SEARCH & ~pymupdf.TEXT_PRESERVE_LIGATURES


def render_page_png(
    data: bytes, page_number: int, highlight_phrases: list[str] | None = None, dpi: int = 110
) -> bytes | None:
    """Render one page to PNG, optionally highlighting phrases. Works on an in-memory copy."""
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception:
        return None
    try:
        if not 1 <= page_number <= doc.page_count:
            return None
        page = doc.load_page(page_number - 1)
        for phrase in highlight_phrases or []:
            words = phrase.strip(" \"'.…").split()
            if len(" ".join(words)) < 4:
                continue
            rects = page.search_for(" ".join(words), flags=_SEARCH_FLAGS)
            if not rects:
                # Multi-line quotes rarely match as one string: search short word groups instead
                # (each group usually sits on one line) and highlight every group found.
                for i in range(0, len(words), 4):
                    group = " ".join(words[i : i + 4])
                    if len(group) >= 4:
                        rects.extend(page.search_for(group, flags=_SEARCH_FLAGS))
            if rects:
                page.add_highlight_annot(rects)
        pix = page.get_pixmap(dpi=dpi)
        return pix.tobytes("png")
    except Exception:
        return None
    finally:
        doc.close()
