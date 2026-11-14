"""Deterministic, page-aware chunking.

Design choices:

* Chunks never cross a page boundary, so every chunk (and therefore every citation) maps to
  exactly one page number.
* Chunk text is an exact substring of the normalized page text (``char_start``/``char_end``
  are offsets into it), which makes quote verification and highlighting straightforward.
* Chunks are packed from sentence-like units up to ``chunk_size`` characters; consecutive
  chunks share whole trailing units totalling at most ``overlap`` characters.
* Units longer than ``chunk_size`` are split at whitespace, so no text is ever dropped.
"""

from __future__ import annotations

import re

from docintel.models import Chunk, DocumentRecord
from docintel.security import INJECTION_FLAG, detect_instruction_like_text

# A sentence ends at . ! ? (optionally followed by a closing quote/bracket) before whitespace.
_SENTENCE_END = re.compile(r"[.!?][\"'”’)\]]?(?=\s)")
_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")


def _split_long_span(text: str, start: int, end: int, max_len: int) -> list[tuple[int, int]]:
    """Split [start, end) into pieces of at most max_len characters, preferring whitespace."""
    spans: list[tuple[int, int]] = []
    pos = start
    while end - pos > max_len:
        cut = text.rfind(" ", pos + max_len // 2, pos + max_len)
        if cut == -1:
            cut = pos + max_len
        spans.append((pos, cut))
        pos = cut
        while pos < end and text[pos].isspace():
            pos += 1
    if pos < end:
        spans.append((pos, end))
    return spans


def split_units(text: str, max_unit_len: int) -> list[tuple[int, int]]:
    """Split page text into (start, end) spans of sentences, respecting paragraph breaks."""
    units: list[tuple[int, int]] = []
    para_start = 0
    paragraph_spans: list[tuple[int, int]] = []
    for match in _PARAGRAPH_BREAK.finditer(text):
        paragraph_spans.append((para_start, match.start()))
        para_start = match.end()
    paragraph_spans.append((para_start, len(text)))

    for p_start, p_end in paragraph_spans:
        segment = text[p_start:p_end]
        cursor = 0
        boundaries = [m.end() for m in _SENTENCE_END.finditer(segment)]
        for boundary in [*boundaries, len(segment)]:
            s, e = cursor, boundary
            # Trim surrounding whitespace while keeping absolute offsets.
            while s < e and segment[s].isspace():
                s += 1
            while e > s and segment[e - 1].isspace():
                e -= 1
            if e > s:
                units.extend(_split_long_span(text, p_start + s, p_start + e, max_unit_len))
            cursor = boundary
    return units


def chunk_page(text: str, chunk_size: int, overlap: int) -> list[tuple[int, int]]:
    """Return chunk spans for one page of text."""
    units = split_units(text, max_unit_len=chunk_size)
    if not units:
        return []
    chunks: list[tuple[int, int]] = []
    i = 0
    while i < len(units):
        start = units[i][0]
        j = i
        # Greedily add units while the chunk stays within chunk_size.
        while j + 1 < len(units) and units[j + 1][1] - start <= chunk_size:
            j += 1
        chunks.append((start, units[j][1]))
        if j + 1 >= len(units):
            break
        # Next chunk starts with trailing units of this chunk totalling <= overlap characters.
        next_i = j + 1
        k = j
        while k > i and units[j][1] - units[k][0] <= overlap:
            next_i = k
            k -= 1
        # Make sure the next chunk can include at least one new unit within chunk_size.
        while next_i <= j and units[j + 1][1] - units[next_i][0] > chunk_size:
            next_i += 1
        i = max(next_i, i + 1)
    return chunks


def document_context_header(doc: DocumentRecord) -> str:
    """Document-level search context for every chunk: the PDF's title metadata, or the humanized
    file name when the PDF has no title. (Using both double-counts title terms; measured in
    evaluation/retrieval_eval.py, see docs/EVALUATION_REPORT.md.)"""
    title = doc.metadata.get("title", "").strip()
    if title:
        return title
    stem = re.sub(r"\.pdf$", "", doc.filename, flags=re.IGNORECASE)
    return re.sub(r"[_\-]+", " ", stem).strip()


def chunk_document(doc: DocumentRecord, chunk_size: int = 1000, overlap: int = 150) -> list[Chunk]:
    """Chunk every non-empty page of ``doc``. Deterministic for the same input and parameters."""
    header = document_context_header(doc)
    chunks: list[Chunk] = []
    ordinal = 0
    for page in doc.pages:
        if not page.text.strip():
            continue
        for idx, (start, end) in enumerate(chunk_page(page.text, chunk_size, overlap)):
            text = page.text[start:end]
            flags = [INJECTION_FLAG] if detect_instruction_like_text(text) else []
            chunks.append(
                Chunk(
                    chunk_id=f"{doc.doc_id}:p{page.page_number}:c{idx}",
                    doc_id=doc.doc_id,
                    filename=doc.filename,
                    page_number=page.page_number,
                    chunk_index=idx,
                    ordinal=ordinal,
                    text=text,
                    char_start=start,
                    char_end=end,
                    flags=flags,
                    context_header=header,
                )
            )
            ordinal += 1
    return chunks
