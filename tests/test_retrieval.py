import pytest

from docintel.chunking import chunk_document
from docintel.retrieval import (
    BM25Retriever,
    CharNgramRetriever,
    HybridRetriever,
    build_retriever,
    estimate_tokens,
    select_context,
    stem,
    to_source_passages,
    tokenize,
)
from tests.conftest import make_record

PAGES = [
    "The monthly service fee is $4,500.00 and invoices are payable within 30 days.",
    "Either party may terminate the agreement for convenience with sixty days notice.",
    "Nightly backups are retained for thirty-five days by the provider.",
    "The tree canopy study covered 48 neighborhoods in Riverton.",
]


@pytest.fixture
def chunks():
    return chunk_document(make_record(PAGES, title="Services Agreement"), 400, 0)


def test_tokenizer_normalizes_numbers_and_stems():
    assert tokenize("Fees of $4,500.00 were PAID monthly") == ["fee", "4500", "paid", "month"]
    assert stem("termination") == stem("terminated") == stem("terminate")
    assert stem("policies") == stem("policy")
    assert stem("status") == "status"


def test_bm25_ranks_exact_match_first(chunks):
    hits = BM25Retriever(chunks).search("What is the monthly service fee?", top_k=3)
    assert hits[0].chunk.page_number == 1
    assert [h.rank for h in hits] == list(range(1, len(hits) + 1))


def test_char_ngrams_match_different_word_forms(chunks):
    hits = CharNgramRetriever(chunks).search("terminating early", top_k=2)
    assert hits[0].chunk.page_number == 2


def test_hybrid_returns_relevant_first(chunks):
    hits = HybridRetriever(chunks).search("How long are backups retained?", top_k=2)
    assert hits[0].chunk.page_number == 3


def test_bm25_cannot_match_without_shared_terms(chunks):
    assert BM25Retriever(chunks).search("xylophone quokka", top_k=5) == []


def test_document_filter_restricts_results():
    a = chunk_document(make_record(["Shared term alpha."], doc_id="doc-a"), 300, 0)
    b = chunk_document(make_record(["Shared term alpha."], doc_id="doc-b"), 300, 0)
    retriever = BM25Retriever(a + b)
    assert {h.chunk.doc_id for h in retriever.search("alpha", 5)} == {"doc-a", "doc-b"}
    assert {h.chunk.doc_id for h in retriever.search("alpha", 5, doc_ids=["doc-b"])} == {"doc-b"}


def test_ties_are_broken_deterministically():
    a = chunk_document(make_record(["Identical text."], doc_id="doc-b"), 300, 0)
    b = chunk_document(make_record(["Identical text."], doc_id="doc-a"), 300, 0)
    hits = BM25Retriever(a + b).search("identical", 2)
    assert [h.chunk.doc_id for h in hits] == ["doc-a", "doc-b"]


def test_title_context_header_is_searchable(chunks):
    hits = BM25Retriever(chunks).search("services agreement", top_k=4)
    assert len(hits) == 4  # every chunk carries the document title in its index text


def test_select_context_respects_budget_and_max_chunks(chunks):
    ranked = HybridRetriever(chunks).search("fee notice backups canopy", top_k=4)
    tight = select_context(ranked, token_budget=60, max_chunks=4)
    assert tight.estimated_tokens <= 60 and tight.skipped_for_budget >= 1
    capped = select_context(ranked, token_budget=10_000, max_chunks=2)
    assert len(capped.selected) == 2


def test_select_context_skips_overlapping_duplicates():
    text = " ".join(f"Sentence number {i} about the shared topic." for i in range(40))
    overlapping = chunk_document(make_record([text]), 300, 140)
    ranked = BM25Retriever(overlapping).search("shared topic sentence", top_k=len(overlapping))
    selection = select_context(ranked, token_budget=10_000, max_chunks=20, duplicate_threshold=0.3)
    assert selection.skipped_duplicates > 0


def test_select_context_caps_chunks_per_document():
    a = chunk_document(
        make_record(["alpha one.", "alpha two.", "alpha three."], doc_id="doc-a"), 300, 0
    )
    b = chunk_document(make_record(["alpha four."], doc_id="doc-b"), 300, 0)
    ranked = BM25Retriever(a + b).search("alpha", top_k=10)
    selection = select_context(ranked, token_budget=10_000, max_chunks=10, max_per_document=2)
    per_doc = [h.chunk.doc_id for h in selection.selected]
    assert per_doc.count("doc-a") == 2 and per_doc.count("doc-b") == 1


def test_source_ids_are_sequential_and_keep_metadata(chunks):
    ranked = BM25Retriever(chunks).search("fee notice", top_k=2)
    passages = to_source_passages(ranked)
    assert [p.source_id for p in passages] == ["S1", "S2"]
    assert passages[0].page_number == ranked[0].chunk.page_number
    assert passages[0].chunk_id == ranked[0].chunk.chunk_id


def test_unknown_retriever_name_raises(chunks):
    with pytest.raises(ValueError):
        build_retriever("embeddings", chunks)


def test_token_estimate_is_positive():
    assert estimate_tokens("") == 1 and estimate_tokens("a" * 400) == 100
