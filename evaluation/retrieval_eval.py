"""Offline retrieval benchmark: BM25 vs character n-grams vs hybrid (deterministic, free).

Two case sets are used:

* the QA cases from ``test_cases.json`` that have expected evidence pages (wording close to
  the documents, as users often copy terms), and
* ``retrieval_paraphrase_cases.json``: questions deliberately paraphrased away from the
  document wording, to expose the weakness of lexical retrieval.

Each set is run in two modes: **scoped** (only the case's documents are loaded, as a user would
upload them; with these short fixtures that is 2-5 chunks, so the task is easy) and
**collection** (all seven text fixtures loaded and searched together, 19 pages), which is the
more discriminating test.

Metrics per retriever: hit@1, hit@3, hit@5 (an expected page appears among the top-k chunks),
MRR, and "context hit" (an expected page is among the passages actually sent to the model
after context selection with the default settings).

    python -m evaluation.retrieval_eval
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from docintel.config import FIXTURES_DIR, Settings
from docintel.retrieval import RETRIEVERS, select_context
from docintel.session import DocumentWorkspace

HERE = Path(__file__).resolve().parent
RESULTS_DIR = HERE / "results"


def _workspace(settings: Settings, documents: list[str], cache: dict) -> DocumentWorkspace:
    key = frozenset(documents)
    if key not in cache:
        ws = DocumentWorkspace(settings)
        for name in documents:
            ws.add_pdf(name, (FIXTURES_DIR / name).read_bytes())
        cache[key] = ws
    return cache[key]


def load_retrieval_cases() -> dict[str, list[dict]]:
    qa = json.loads((HERE / "test_cases.json").read_text(encoding="utf-8"))["cases"]
    standard = [
        {
            "id": c["id"],
            "documents": c["documents"],
            "question": c["question"],
            "evidence": c["expected"]["evidence"],
        }
        for c in qa
        if c["task"] == "qa"
        and c["expected"].get("evidence")
        and c["expected"].get("required_facts")
    ]
    paraphrase = json.loads((HERE / "retrieval_paraphrase_cases.json").read_text(encoding="utf-8"))[
        "cases"
    ]
    return {"standard": standard, "paraphrase": paraphrase}


def evaluate(settings: Settings | None = None) -> dict:
    settings = settings or Settings(provider="mock")
    cache: dict = {}
    sets = load_retrieval_cases()
    report: dict = {
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "settings": {
            "chunk_size": settings.chunk_size,
            "chunk_overlap": settings.chunk_overlap,
            "top_k": settings.top_k,
            "context_token_budget": settings.context_token_budget,
        },
        "case_counts": {k: len(v) for k, v in sets.items()},
        "results": {},
        "per_case": {},
    }
    all_docs = sorted(p.name for p in FIXTURES_DIR.glob("*.pdf") if "scanned" not in p.name)
    runs = [
        (f"{set_name}/{mode}", cases, mode)
        for set_name, cases in sets.items()
        for mode in ("scoped", "collection")
    ]
    report["case_counts"] = {label: len(cases) for label, cases, _ in runs}
    for set_name, cases, mode in runs:
        for name in RETRIEVERS:
            hits = {1: 0, 3: 0, 5: 0}
            rr_total = 0.0
            context_hits = 0
            per_case = []
            for case in cases:
                ws = _workspace(
                    settings, case["documents"] if mode == "scoped" else all_docs, cache
                )
                expected = {(e["document"], e["page"]) for e in case["evidence"]}
                ranked = ws.search(
                    case["question"], top_k=max(settings.top_k * 3, 20), retriever=name
                )
                pages = [(h.chunk.filename, h.chunk.page_number) for h in ranked]
                first = next((i for i, p in enumerate(pages, start=1) if p in expected), None)
                for k in hits:
                    hits[k] += 1 if first is not None and first <= k else 0
                rr_total += 1.0 / first if first else 0.0
                selection = select_context(
                    ranked,
                    token_budget=settings.context_token_budget,
                    max_chunks=settings.top_k,
                    max_per_document=settings.max_chunks_per_document
                    if len(ws.doc_ids) > 1
                    else None,
                )
                in_context = any(
                    (s.chunk.filename, s.chunk.page_number) in expected for s in selection.selected
                )
                context_hits += 1 if in_context else 0
                per_case.append(
                    {"id": case["id"], "first_relevant_rank": first, "in_context": in_context}
                )
            n = len(cases) or 1
            report["results"].setdefault(set_name, {})[name] = {
                "hit@1": round(hits[1] / n, 3),
                "hit@3": round(hits[3] / n, 3),
                "hit@5": round(hits[5] / n, 3),
                "mrr": round(rr_total / n, 3),
                "context_hit": round(context_hits / n, 3),
            }
            report["per_case"].setdefault(set_name, {})[name] = per_case
    return report


def render_markdown(report: dict) -> str:
    lines = [
        "# Retrieval benchmark (offline, deterministic)",
        "",
        f"Run: {report['timestamp']} - chunk size {report['settings']['chunk_size']} chars, overlap "
        f"{report['settings']['chunk_overlap']}, top_k {report['settings']['top_k']}, context budget "
        f"{report['settings']['context_token_budget']} tokens.",
        "",
    ]
    for set_name, by_retriever in report["results"].items():
        lines += [
            f"## {set_name} ({report['case_counts'][set_name]} cases)",
            "",
            "| Retriever | hit@1 | hit@3 | hit@5 | MRR | in final context |",
            "|---|---|---|---|---|---|",
        ]
        for name, m in by_retriever.items():
            lines.append(
                f"| {name} | {m['hit@1']} | {m['hit@3']} | {m['hit@5']} | {m['mrr']} | {m['context_hit']} |"
            )
        misses = {
            name: [c["id"] for c in cases if not c["in_context"]]
            for name, cases in report["per_case"][set_name].items()
        }
        lines += [
            "",
            "Cases where no expected page reached the model's context: "
            + "; ".join(f"{k}: {', '.join(v) or 'none'}" for k, v in misses.items()),
            "",
        ]
    lines.append(
        "Notes: 'scoped' loads only the case's documents (2-5 chunks), so nearly the whole document "
        "fits in the context and its numbers are optimistic. 'collection' searches all fixtures (19 pages) "
        "and is the more informative comparison. Fixture pages are short (one or two chunks each), so "
        "page-level hit rates are still optimistic compared with long real-world documents."
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    report = evaluate()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    (RESULTS_DIR / f"{stamp}_retrieval_benchmark.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    md = render_markdown(report)
    (RESULTS_DIR / f"{stamp}_retrieval_benchmark.md").write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
