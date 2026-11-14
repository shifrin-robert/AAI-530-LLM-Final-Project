# Retrieval benchmark (offline, deterministic)

Run: 2026-11-14T01:17:47+00:00 - chunk size 1000 chars, overlap 150, top_k 8, context budget 6000 tokens.

## standard/scoped (26 cases)

| Retriever | hit@1 | hit@3 | hit@5 | MRR | in final context |
|---|---|---|---|---|---|
| bm25 | 0.885 | 0.962 | 1.0 | 0.933 | 1.0 |
| char_ngram | 0.808 | 0.962 | 1.0 | 0.894 | 1.0 |
| hybrid | 0.846 | 0.962 | 1.0 | 0.913 | 1.0 |

Cases where no expected page reached the model's context: bm25: none; char_ngram: none; hybrid: none

## standard/collection (26 cases)

| Retriever | hit@1 | hit@3 | hit@5 | MRR | in final context |
|---|---|---|---|---|---|
| bm25 | 0.885 | 0.962 | 1.0 | 0.933 | 1.0 |
| char_ngram | 0.808 | 1.0 | 1.0 | 0.904 | 1.0 |
| hybrid | 0.846 | 1.0 | 1.0 | 0.917 | 1.0 |

Cases where no expected page reached the model's context: bm25: none; char_ngram: none; hybrid: none

## paraphrase/scoped (12 cases)

| Retriever | hit@1 | hit@3 | hit@5 | MRR | in final context |
|---|---|---|---|---|---|
| bm25 | 0.5 | 0.667 | 0.75 | 0.604 | 0.75 |
| char_ngram | 0.5 | 0.917 | 0.917 | 0.681 | 0.917 |
| hybrid | 0.417 | 0.833 | 0.917 | 0.632 | 0.917 |

Cases where no expected page reached the model's context: bm25: PARA-03, PARA-07, PARA-08; char_ngram: PARA-08; hybrid: PARA-08

## paraphrase/collection (12 cases)

| Retriever | hit@1 | hit@3 | hit@5 | MRR | in final context |
|---|---|---|---|---|---|
| bm25 | 0.333 | 0.583 | 0.75 | 0.468 | 0.75 |
| char_ngram | 0.333 | 0.583 | 0.75 | 0.508 | 0.917 |
| hybrid | 0.333 | 0.667 | 0.833 | 0.508 | 0.917 |

Cases where no expected page reached the model's context: bm25: PARA-03, PARA-07, PARA-08; char_ngram: PARA-08; hybrid: PARA-08

Notes: 'scoped' loads only the case's documents (2-5 chunks), so nearly the whole document fits in the context and its numbers are optimistic. 'collection' searches all fixtures (19 pages) and is the more informative comparison. Fixture pages are short (one or two chunks each), so page-level hit rates are still optimistic compared with long real-world documents.
