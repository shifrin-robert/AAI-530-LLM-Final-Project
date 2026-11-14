"""Deterministic local retrieval: BM25, character n-gram TF-IDF, and a hybrid of the two.

No external services, vector databases or model downloads are involved, so retrieval runs
offline and gives identical results on every run. ``evaluation/retrieval_eval.py`` compares
the three retrievers on labelled questions (see docs/EVALUATION_REPORT.md).

* **BM25** (Okapi) over lightly stemmed word tokens: strong on exact terminology, numbers
  and names; weak on paraphrases and different word forms.
* **Character n-grams** (TF-IDF over 4-grams within words, cosine similarity): tolerant of
  morphology ("terminate" vs "termination") and minor spelling variation, but noisier.
* **Hybrid**: reciprocal-rank fusion (RRF) of the two rankings.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from docintel.models import Chunk, SourcePassage

# --------------------------------------------------------------------------- tokenization

STOPWORDS = frozenset(
    [
        "a",
        "about",
        "above",
        "after",
        "again",
        "against",
        "all",
        "am",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "because",
        "been",
        "before",
        "being",
        "below",
        "between",
        "both",
        "but",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "doing",
        "down",
        "during",
        "each",
        "few",
        "for",
        "from",
        "further",
        "had",
        "has",
        "have",
        "having",
        "he",
        "her",
        "here",
        "hers",
        "herself",
        "him",
        "himself",
        "his",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "itself",
        "just",
        "me",
        "more",
        "most",
        "my",
        "myself",
        "no",
        "nor",
        "not",
        "now",
        "of",
        "off",
        "on",
        "once",
        "only",
        "or",
        "other",
        "our",
        "ours",
        "ourselves",
        "out",
        "over",
        "own",
        "same",
        "she",
        "should",
        "so",
        "some",
        "such",
        "than",
        "that",
        "the",
        "their",
        "theirs",
        "them",
        "themselves",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "to",
        "too",
        "under",
        "until",
        "up",
        "very",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "who",
        "whom",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
        "yours",
        "yourself",
        "yourselves",
        "also",
        "may",
        "might",
        "must",
        "shall",
        "s",
        "t",
        "per",
        "via",
        "upon",
        "within",
        "without",
        "whether",
        "e",
        "g",
        "ie",
        "etc",
    ]
)

_WORD_RE = re.compile(r"[a-z0-9]+(?:[.,][0-9]+)*")


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    return text.replace("’", "'").replace("‘", "'")


def _normalize_number(token: str) -> str:
    """'4,500.00' -> '4500'; '1.5' -> '1.5'; '2026' -> '2026'."""
    if not token[0].isdigit():
        return token
    stripped = token.replace(",", "")
    if re.fullmatch(r"\d+\.\d+", stripped):
        whole, frac = stripped.split(".")
        frac = frac.rstrip("0")
        return whole if not frac else f"{whole}.{frac}"
    return stripped


def stem(token: str) -> str:
    """A deliberately conservative suffix stripper (Porter-lite).

    Maps common inflections together (fees/fee, terminated/termination/terminate -> terminat,
    monthly -> month) without the aggressive conflations of a full stemmer.
    """
    if len(token) <= 3 or token[0].isdigit():
        return token
    for suffix, replacement, min_stem in (
        ("ational", "ate", 3),
        ("ization", "ize", 3),
        ("ations", "ate", 3),
        ("ation", "ate", 3),
        ("ments", "", 4),
        ("ment", "", 4),
        ("ities", "", 3),
        ("ity", "", 3),
        ("ies", "y", 2),
        ("ied", "y", 2),
        ("sses", "ss", 2),
        ("ness", "", 3),
        ("ings", "", 3),
        ("ing", "", 3),
        ("ions", "", 3),
        ("ion", "", 3),
        ("edly", "", 3),
        ("ly", "", 4),
        ("ed", "", 3),
        ("ers", "er", 3),
        ("es", "e", 3),
        ("s", "", 3),
    ):
        if token.endswith(suffix) and len(token) - len(suffix) >= min_stem:
            if suffix == "s" and token.endswith(("ss", "us", "is")):
                return token
            if suffix == "ly" and token.endswith("ply"):  # apply, supply, reply, comply
                break
            token = token[: len(token) - len(suffix)] + replacement
            break
    # Treat a trailing silent "e" as optional so terminate/terminat/terminated align.
    if len(token) > 4 and token.endswith("e"):
        token = token[:-1]
    return token


def tokenize(text: str, *, remove_stopwords: bool = True, use_stemming: bool = True) -> list[str]:
    tokens: list[str] = []
    for raw in _WORD_RE.findall(_normalize(text)):
        token = _normalize_number(raw)
        if remove_stopwords and token in STOPWORDS:
            continue
        tokens.append(stem(token) if use_stemming else token)
    return tokens


def char_ngrams(text: str, n: int = 4) -> list[str]:
    grams: list[str] = []
    for word in _WORD_RE.findall(_normalize(text)):
        word = _normalize_number(word)
        if word in STOPWORDS:
            continue
        padded = f" {word} "
        if len(padded) <= n:
            grams.append(padded)
            continue
        grams.extend(padded[i : i + n] for i in range(len(padded) - n + 1))
    return grams


# --------------------------------------------------------------------------- retrievers


@dataclass(frozen=True)
class ScoredChunk:
    chunk: Chunk
    score: float
    rank: int  # 1-based


class _BaseRetriever:
    name = "base"

    def __init__(self, chunks: Sequence[Chunk]):
        self.chunks: list[Chunk] = list(chunks)

    def _scores(self, query: str) -> dict[int, float]:  # pragma: no cover - abstract
        raise NotImplementedError

    def search(
        self, query: str, top_k: int = 8, doc_ids: Iterable[str] | None = None
    ) -> list[ScoredChunk]:
        allowed = set(doc_ids) if doc_ids is not None else None
        scores = self._scores(query)
        candidates = [
            (score, idx)
            for idx, score in scores.items()
            if score > 0 and (allowed is None or self.chunks[idx].doc_id in allowed)
        ]
        # Deterministic: higher score first, then document order (doc_id, ordinal).
        candidates.sort(key=lambda t: (-t[0], self.chunks[t[1]].doc_id, self.chunks[t[1]].ordinal))
        return [
            ScoredChunk(chunk=self.chunks[idx], score=round(score, 6), rank=rank)
            for rank, (score, idx) in enumerate(candidates[:top_k], start=1)
        ]


class BM25Retriever(_BaseRetriever):
    name = "bm25"

    def __init__(self, chunks: Sequence[Chunk], k1: float = 1.5, b: float = 0.75):
        super().__init__(chunks)
        self.k1, self.b = k1, b
        self._postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        self._lengths: list[int] = []
        for idx, chunk in enumerate(self.chunks):
            counts = Counter(tokenize(chunk.index_text))
            self._lengths.append(sum(counts.values()))
            for term, tf in counts.items():
                self._postings[term].append((idx, tf))
        n = len(self.chunks)
        self._avg_len = (sum(self._lengths) / n) if n else 0.0
        self._idf = {
            term: math.log(1 + (n - len(post) + 0.5) / (len(post) + 0.5))
            for term, post in self._postings.items()
        }

    def _scores(self, query: str) -> dict[int, float]:
        scores: dict[int, float] = defaultdict(float)
        if not self.chunks:
            return scores
        for term in set(tokenize(query)):
            postings = self._postings.get(term)
            if not postings:
                continue
            idf = self._idf[term]
            for idx, tf in postings:
                norm = 1 - self.b + self.b * (self._lengths[idx] / (self._avg_len or 1))
                scores[idx] += idf * (tf * (self.k1 + 1)) / (tf + self.k1 * norm)
        return scores


class CharNgramRetriever(_BaseRetriever):
    name = "char_ngram"

    def __init__(self, chunks: Sequence[Chunk], n: int = 4):
        super().__init__(chunks)
        self.n = n
        doc_freq: Counter[str] = Counter()
        raw_vectors: list[Counter[str]] = []
        for chunk in self.chunks:
            counts = Counter(char_ngrams(chunk.index_text, n))
            raw_vectors.append(counts)
            doc_freq.update(counts.keys())
        total = len(self.chunks)
        self._idf = {g: math.log((total + 1) / (df + 1)) + 1 for g, df in doc_freq.items()}
        self._postings: dict[str, list[tuple[int, float]]] = defaultdict(list)
        for idx, counts in enumerate(raw_vectors):
            weights = {g: (1 + math.log(tf)) * self._idf[g] for g, tf in counts.items()}
            norm = math.sqrt(sum(w * w for w in weights.values())) or 1.0
            for g, w in weights.items():
                self._postings[g].append((idx, w / norm))

    def _scores(self, query: str) -> dict[int, float]:
        counts = Counter(char_ngrams(query, self.n))
        weights = {
            g: (1 + math.log(tf)) * self._idf[g] for g, tf in counts.items() if g in self._idf
        }
        norm = math.sqrt(sum(w * w for w in weights.values())) or 1.0
        scores: dict[int, float] = defaultdict(float)
        for g, w in weights.items():
            for idx, dw in self._postings[g]:
                scores[idx] += (w / norm) * dw
        return scores


class HybridRetriever(_BaseRetriever):
    """Reciprocal-rank fusion of BM25 and character n-gram rankings."""

    name = "hybrid"

    def __init__(self, chunks: Sequence[Chunk], rrf_k: int = 60, depth: int = 50):
        super().__init__(chunks)
        self.rrf_k, self.depth = rrf_k, depth
        self.bm25 = BM25Retriever(self.chunks)
        self.char = CharNgramRetriever(self.chunks)

    def _scores(self, query: str) -> dict[int, float]:
        fused: dict[int, float] = defaultdict(float)
        index_of = {id(c): i for i, c in enumerate(self.chunks)}
        for retriever in (self.bm25, self.char):
            for hit in retriever.search(query, top_k=self.depth):
                fused[index_of[id(hit.chunk)]] += 1.0 / (self.rrf_k + hit.rank)
        return fused


RETRIEVERS = {"bm25": BM25Retriever, "char_ngram": CharNgramRetriever, "hybrid": HybridRetriever}


def build_retriever(name: str, chunks: Sequence[Chunk]) -> _BaseRetriever:
    try:
        return RETRIEVERS[name](chunks)
    except KeyError:
        raise ValueError(f"Unknown retriever '{name}'. Choose from {sorted(RETRIEVERS)}.") from None


# --------------------------------------------------------------------------- context selection


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 characters per token for English). Used for budgeting only;
    actual usage is taken from the provider's response."""
    return max(1, math.ceil(len(text) / 4))


def _overlap_ratio(a: Chunk, b: Chunk) -> float:
    if a.doc_id != b.doc_id or a.page_number != b.page_number:
        return 0.0
    inter = min(a.char_end, b.char_end) - max(a.char_start, b.char_start)
    if inter <= 0:
        return 0.0
    return inter / min(a.char_end - a.char_start, b.char_end - b.char_start)


@dataclass
class ContextSelection:
    selected: list[ScoredChunk]
    skipped_duplicates: int = 0
    skipped_for_budget: int = 0
    skipped_for_doc_cap: int = 0
    estimated_tokens: int = 0
    notes: list[str] = field(default_factory=list)


def select_context(
    ranked: Sequence[ScoredChunk],
    *,
    token_budget: int,
    max_chunks: int,
    max_per_document: int | None = None,
    duplicate_threshold: float = 0.6,
) -> ContextSelection:
    """Pick the highest-ranked chunks that fit the token budget, skipping near-duplicates
    (overlapping chunks from the same page) and capping chunks per document for diversity."""
    result = ContextSelection(selected=[])
    per_doc: Counter[str] = Counter()
    for hit in ranked:
        if len(result.selected) >= max_chunks:
            break
        if any(_overlap_ratio(hit.chunk, s.chunk) >= duplicate_threshold for s in result.selected):
            result.skipped_duplicates += 1
            continue
        if max_per_document is not None and per_doc[hit.chunk.doc_id] >= max_per_document:
            result.skipped_for_doc_cap += 1
            continue
        cost = estimate_tokens(hit.chunk.text) + 30  # + per-source framing overhead
        if result.estimated_tokens + cost > token_budget:
            result.skipped_for_budget += 1
            continue
        result.selected.append(hit)
        result.estimated_tokens += cost
        per_doc[hit.chunk.doc_id] += 1
    if result.skipped_for_budget:
        result.notes.append(
            f"{result.skipped_for_budget} relevant passage(s) did not fit the context budget."
        )
    return result


def to_source_passages(
    selected: Sequence[ScoredChunk], start_index: int = 1
) -> list[SourcePassage]:
    """Assign request-scoped source IDs (S1, S2, ...) in rank order."""
    return [
        SourcePassage(
            source_id=f"S{i}",
            chunk_id=hit.chunk.chunk_id,
            doc_id=hit.chunk.doc_id,
            filename=hit.chunk.filename,
            page_number=hit.chunk.page_number,
            text=hit.chunk.text,
            score=hit.score,
            flags=list(hit.chunk.flags),
        )
        for i, hit in enumerate(selected, start=start_index)
    ]


def chunks_to_passages(chunks: Sequence[Chunk], start_index: int = 1) -> list[SourcePassage]:
    """Source passages for whole-document tasks (summaries, extraction), in document order."""
    return [
        SourcePassage(
            source_id=f"S{i}",
            chunk_id=c.chunk_id,
            doc_id=c.doc_id,
            filename=c.filename,
            page_number=c.page_number,
            text=c.text,
            score=None,
            flags=list(c.flags),
        )
        for i, c in enumerate(chunks, start=start_index)
    ]
