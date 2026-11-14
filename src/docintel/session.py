"""Per-user document workspace.

A ``DocumentWorkspace`` holds one user's uploaded documents, their chunks and the retrieval
index, entirely in memory. The Streamlit app stores exactly one workspace in each browser
session's ``st.session_state``; nothing is placed in Streamlit's cross-session caches
(``st.cache_data`` / ``st.cache_resource``), so documents cannot leak between sessions. Clearing
the session (or closing the tab) drops the only references to the uploaded bytes.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from docintel.chunking import chunk_document
from docintel.config import Settings
from docintel.models import Chunk, DocumentRecord
from docintel.pdf_processing import (
    PDFValidationError,
    compute_sha256,
    extract_document,
    make_doc_id,
)
from docintel.retrieval import ScoredChunk, build_retriever
from docintel.security import INJECTION_FLAG, get_logger, sanitize_filename

log = get_logger("session")


@dataclass
class LoadedDocument:
    record: DocumentRecord
    data: bytes  # kept only in memory, for rendering cited pages
    chunks: list[Chunk]

    @property
    def flagged_chunks(self) -> int:
        return sum(1 for c in self.chunks if INJECTION_FLAG in c.flags)


@dataclass
class AddResult:
    filename: str
    record: DocumentRecord | None = None
    error: str | None = None
    duplicate: bool = False

    @property
    def ok(self) -> bool:
        return self.record is not None and self.error is None


@dataclass
class DocumentWorkspace:
    settings: Settings
    _docs: dict[str, LoadedDocument] = field(default_factory=dict)
    _retrievers: dict[str, object] = field(default_factory=dict)

    # ------------------------------------------------------------------ documents
    def add_pdf(self, filename: str, data: bytes) -> AddResult:
        safe_name = sanitize_filename(filename)
        doc_id = make_doc_id(compute_sha256(data)) if data else None
        if doc_id and doc_id in self._docs:
            return AddResult(safe_name, record=self._docs[doc_id].record, duplicate=True)
        if len(self._docs) >= self.settings.max_documents:
            return AddResult(
                safe_name,
                error=f"Document limit reached ({self.settings.max_documents}). Remove a document first.",
            )
        try:
            record = extract_document(safe_name, data, self.settings)
        except PDFValidationError as exc:
            return AddResult(safe_name, error=exc.user_message)
        if self.total_pages + record.page_count > self.settings.max_total_pages:
            return AddResult(
                safe_name,
                error=f"Adding '{safe_name}' would exceed the session limit of "
                f"{self.settings.max_total_pages} pages. Remove a document first.",
            )
        chunks = chunk_document(record, self.settings.chunk_size, self.settings.chunk_overlap)
        self._docs[record.doc_id] = LoadedDocument(record=record, data=data, chunks=chunks)
        self._retrievers.clear()
        log.info(
            "document_added doc_id=%s pages=%d chunks=%d",
            record.doc_id,
            record.page_count,
            len(chunks),
        )
        return AddResult(safe_name, record=record)

    def remove(self, doc_id: str) -> bool:
        removed = self._docs.pop(doc_id, None) is not None
        if removed:
            self._retrievers.clear()
            log.info("document_removed doc_id=%s", doc_id)
        return removed

    def clear(self) -> None:
        self._docs.clear()
        self._retrievers.clear()
        log.info("workspace_cleared")

    # ------------------------------------------------------------------ accessors
    @property
    def documents(self) -> list[DocumentRecord]:
        return [d.record for d in self._docs.values()]

    @property
    def doc_ids(self) -> list[str]:
        return list(self._docs)

    def get(self, doc_id: str) -> LoadedDocument | None:
        return self._docs.get(doc_id)

    @property
    def total_pages(self) -> int:
        return sum(d.record.page_count for d in self._docs.values())

    @property
    def all_chunks(self) -> list[Chunk]:
        return [c for d in self._docs.values() for c in d.chunks]

    def chunks_for(self, doc_ids: Iterable[str] | None = None) -> list[Chunk]:
        """Chunks of the given documents, in upload order then document order."""
        wanted = list(doc_ids) if doc_ids is not None else self.doc_ids
        return [c for doc_id in wanted if doc_id in self._docs for c in self._docs[doc_id].chunks]

    def resolve_scope(self, doc_ids: Iterable[str] | None) -> list[str]:
        if doc_ids is None:
            return self.doc_ids
        return [d for d in doc_ids if d in self._docs]

    # ------------------------------------------------------------------ retrieval
    def retriever(self, name: str | None = None):
        name = name or self.settings.retriever
        if name not in self._retrievers:
            self._retrievers[name] = build_retriever(name, self.all_chunks)
        return self._retrievers[name]

    def search(
        self,
        query: str,
        top_k: int,
        doc_ids: Iterable[str] | None = None,
        retriever: str | None = None,
    ) -> list[ScoredChunk]:
        return self.retriever(retriever).search(query, top_k=top_k, doc_ids=doc_ids)

    def stats(self) -> dict[str, int]:
        return {
            "documents": len(self._docs),
            "pages": self.total_pages,
            "chunks": len(self.all_chunks),
            "characters": sum(d.record.char_count for d in self._docs.values()),
            "flagged_chunks": sum(d.flagged_chunks for d in self._docs.values()),
        }
