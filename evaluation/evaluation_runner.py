"""End-to-end evaluation runner.

Examples (run from the repository root):

    # Offline, free, deterministic baseline (no API key needed)
    python -m evaluation.evaluation_runner --provider mock

    # Live model run: requires an API key AND explicit permission to spend money
    python -m evaluation.evaluation_runner --provider openai --model gpt-6-luna \
        --prompt-version v2 --allow-paid --max-cost-usd 1.00

    # Prompt-iteration experiment: same cases and settings, two prompt versions
    python -m evaluation.evaluation_runner --provider openai --prompt-version v1 --allow-paid
    python -m evaluation.evaluation_runner --provider openai --prompt-version v2 --allow-paid
    python -m evaluation.compare_runs evaluation/results/<run_v1>.json evaluation/results/<run_v2>.json

Each run writes ``evaluation/results/<run_id>.json`` (full per-case results and metadata) and
``<run_id>.md`` (readable summary). Results are never edited by hand.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import platform
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

from docintel.comparison import compare_documents
from docintel.config import FIXTURES_DIR, PROJECT_ROOT, Settings
from docintel.extraction import extract_information
from docintel.grounding import GroundingReport
from docintel.llm_client import (
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMError,
    LLMProvider,
    LLMQuotaError,
    StructuredRequest,
    create_provider,
)
from docintel.model_catalog import estimate_cost_usd
from docintel.models import JudgeVerdict
from docintel.prompting import load_prompt
from docintel.qa import answer_question
from docintel.session import DocumentWorkspace
from docintel.summarization import summarize_documents
from evaluation import scoring

CASES_PATH = Path(__file__).resolve().parent / "test_cases.json"
RESULTS_DIR = Path(__file__).resolve().parent / "results"
# Conservative per-case token assumptions used only for the pre-run cost estimate.
EST_INPUT_TOKENS_PER_CASE = 6_000
EST_OUTPUT_TOKENS_PER_CASE = 1_500
# Errors that would hit every remaining case (bad key, spend/credit limit, unknown model). The run
# stops without writing results, so a partial run is never mistaken for a complete one.
RUN_STOPPING_ERROR_KINDS = frozenset(
    {LLMAuthenticationError.kind, LLMQuotaError.kind, LLMConfigurationError.kind}
)
EXIT_STOPPED = 3


def load_cases(path: Path = CASES_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _versions() -> dict[str, str]:
    versions = {"python": platform.python_version()}
    for pkg in ("openai", "anthropic", "google-genai", "pymupdf", "pydantic", "streamlit"):
        with contextlib.suppress(metadata.PackageNotFoundError):
            versions[pkg] = metadata.version(pkg)
    return versions


def _grounding_summary(report: GroundingReport) -> dict:
    return {
        "verdict": report.verdict,
        "total_citations": report.total_citations,
        "valid_citations": report.valid_citations,
        "quotes_checked": report.quotes_checked,
        "quotes_found": report.quotes_found,
        "assessed": report.assessed,
        "likely_supported": report.likely_supported,
        "unknown_source_ids": report.unknown_source_ids,
        "unsupported_numbers": report.unsupported_numbers,
        "warnings": report.warnings,
    }


class WorkspaceCache:
    """One fresh workspace per distinct document set, mirroring what a user would upload."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._cache: dict[frozenset[str], DocumentWorkspace] = {}

    def get(self, documents: list[str]) -> DocumentWorkspace:
        key = frozenset(documents)
        if key not in self._cache:
            ws = DocumentWorkspace(self.settings)
            for name in documents:
                result = ws.add_pdf(name, (FIXTURES_DIR / name).read_bytes())
                if not result.ok:
                    raise RuntimeError(f"Fixture {name} failed to load: {result.error}")
            self._cache[key] = ws
        return self._cache[key]


def judge_citations(provider: LLMProvider, result, max_checks: int = 12) -> dict:
    """Optional LLM-as-judge pass over (statement, cited passage) pairs. Evaluation only."""
    template = load_prompt("citation_judge")
    passages = {p.source_id: p for p in result.sources}
    verdicts: list[str] = []
    for check in result.report.checks[:max_checks]:
        if not check.known or not check.statement:
            continue
        system, user = template.render(
            statement=check.statement, passage=passages[check.source_id].text
        )
        out = provider.generate(StructuredRequest("judge", system, user, JudgeVerdict, context={}))
        verdicts.append(out.output.verdict)
    return {
        "judged": len(verdicts),
        "supported": verdicts.count("supported"),
        "partially_supported": verdicts.count("partially_supported"),
        "not_supported": verdicts.count("not_supported"),
    }


def run_case(
    case: dict,
    provider: LLMProvider,
    workspaces: WorkspaceCache,
    *,
    prompt_version: str,
    retriever: str,
    judge: bool,
) -> dict:
    ws = workspaces.get(case["documents"])
    doc_ids = ws.doc_ids
    record: dict = {
        "case_id": case["id"],
        "category": case["category"],
        "task": case["task"],
        "error": None,
    }
    started = time.perf_counter()
    try:
        if case["task"] == "qa":
            result = answer_question(
                ws,
                provider,
                case["question"],
                doc_ids=doc_ids,
                prompt_version=prompt_version,
                retriever=retriever,
            )
            score = scoring.score_qa(case, result.output, result.report)
        elif case["task"] == "summary":
            result = summarize_documents(ws, provider, doc_ids, focus=case.get("focus", ""))
            score = scoring.score_summary(
                case, result.output, result.report, result.coverage.complete
            )
        elif case["task"] == "extraction":
            result = extract_information(ws, provider, doc_ids)
            score = scoring.score_extraction(case, result.output, result.report)
        elif case["task"] == "comparison":
            result = compare_documents(ws, provider, doc_ids, focus=case.get("focus", ""))
            score = scoring.score_comparison(case, result.output, result.report)
        else:
            raise ValueError(f"unknown task {case['task']}")
    except LLMError as exc:
        record.update(
            error=f"{exc.kind}: {exc.user_message}",
            latency_s=round(time.perf_counter() - started, 3),
        )
        return record
    stats = result.stats
    record.update(
        score=score,
        grounding=_grounding_summary(result.report),
        output=result.output.model_dump(),
        cited_pages=sorted(
            {f"{c.filename} p{c.page_number}" for c in result.report.checks if c.known}
        ),
        latency_s=round(stats.latency_s, 3) if stats else 0.0,
        input_tokens=stats.usage.input_tokens if stats else 0,
        output_tokens=stats.usage.output_tokens if stats else 0,
        tokens_estimated=stats.usage.estimated if stats else True,
        cost_usd=stats.cost_usd if stats else 0.0,
    )
    if judge and not provider.is_offline and hasattr(result, "report"):
        try:
            record["judge"] = judge_citations(provider, result)
        except LLMError as exc:
            record["judge"] = {"error": exc.kind}
    return record


def render_markdown(run: dict) -> str:
    m, meta = run["metrics"], run["metadata"]
    lines = [
        f"# Evaluation run `{meta['run_id']}`",
        "",
        f"- Date (UTC): {meta['timestamp']}",
        f"- Provider / model: **{meta['provider']} / {meta['model']}**"
        + (" (offline extractive baseline, not an LLM)" if meta["offline"] else ""),
        f"- QA prompt version: {meta['prompt_version']}; retriever: {meta['retriever']}",
        f"- Dataset version: {meta['dataset_version']}; cases: {meta['case_count']}; repeats: {meta['repeats']}",
        f"- Git commit: {meta.get('git_commit') or 'n/a'}",
        "",
        "## Metrics",
        "",
        "| Metric | Value |",
        "|---|---|",
    ]
    for key in (
        "overall_pass_rate",
        "answer_accuracy",
        "false_abstention_rate",
        "correct_abstention_rate",
        "conflict_handling_rate",
        "injection_resistance_rate",
        "citation_id_validity",
        "quote_match_rate",
        "heuristic_support_rate",
        "evidence_page_hit_rate",
        "extraction_recall_mean",
        "format_compliance",
        "errors",
        "latency_mean_s",
        "latency_max_s",
        "input_tokens",
        "output_tokens",
        "cost_usd",
    ):
        lines.append(f"| {key} | {m.get(key)} |")
    if run.get("consistency", {}).get("cases_with_repeats"):
        c = run["consistency"]
        lines.append(f"| consistency (outcome agreement over repeats) | {c['outcome_agreement']} |")
        lines.append(f"| consistency (status agreement over repeats) | {c['status_agreement']} |")
    lines += [
        "",
        "## By category",
        "",
        "| Category | Cases | Passed | Errors |",
        "|---|---|---|---|",
    ]
    for cat, v in sorted(m["by_category"].items()):
        lines.append(f"| {cat} | {v['cases']} | {v['passed']} | {v['errors']} |")
    lines += ["", "## Failed or errored cases", ""]
    failures = [r for r in run["results"] if r.get("error") or not r["score"]["pass"]]
    if not failures:
        lines.append("None.")
    for r in failures:
        if r.get("error"):
            lines.append(f"- **{r['case_id']}** ({r['category']}): error: {r['error']}")
            continue
        s = r["score"]
        detail = []
        if s.get("missing_facts"):
            detail.append(f"missing facts {s['missing_facts']}")
        if "status_ok" in s and not s["status_ok"]:
            detail.append(f"status '{s['status']}' not accepted")
        if s.get("forbidden_hits"):
            detail.append(f"forbidden phrases {s['forbidden_hits']}")
        if s.get("fabricated_ids"):
            detail.append(f"unknown source IDs {s['fabricated_ids']}")
        if "recall" in s:
            detail.append(f"extraction recall {s['recall']}")
        if s.get("amendment_not_contradiction_ok") is False:
            detail.append("labelled an amended term as a direct contradiction")
        lines.append(
            f"- **{r['case_id']}** ({r['category']}): " + ("; ".join(detail) or "see JSON")
        )
    lines += [
        "",
        "Automatic scores only. Cases whose evaluation_method includes 'human' still need a human rating "
        "(see evaluation/human_review_template.csv).",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the DocIntel evaluation suite.")
    parser.add_argument(
        "--provider", default="mock", choices=["mock", "openai", "anthropic", "gemini"]
    )
    parser.add_argument("--model", default=None)
    parser.add_argument("--prompt-version", default="v3", choices=["v1", "v2", "v3"])
    parser.add_argument("--retriever", default=None, choices=["bm25", "char_ngram", "hybrid"])
    parser.add_argument("--cases", default=None, help="comma-separated case IDs (default: all)")
    parser.add_argument(
        "--repeats", type=int, default=1, help="run each case N times (consistency)"
    )
    parser.add_argument(
        "--allow-paid", action="store_true", help="required for any non-mock provider"
    )
    parser.add_argument(
        "--max-cost-usd", type=float, default=1.0, help="abort if the estimate exceeds this"
    )
    parser.add_argument(
        "--judge", action="store_true", help="add an LLM-as-judge citation check (paid)"
    )
    parser.add_argument("--out", type=Path, default=RESULTS_DIR)
    parser.add_argument("--tag", default="", help="optional label appended to the run ID")
    args = parser.parse_args(argv)

    dataset = load_cases()
    cases = dataset["cases"]
    if args.cases:
        wanted = {c.strip() for c in args.cases.split(",")}
        cases = [c for c in cases if c["id"] in wanted]
    settings = Settings.from_env().with_overrides(
        provider=args.provider,
        model=args.model,
        qa_prompt_version=args.prompt_version,
        max_requests_per_session=100_000,
        **({"retriever": args.retriever} if args.retriever else {}),
    )
    retriever = args.retriever or settings.retriever

    if args.provider != "mock":
        # Priced per case, not on the summed tokens: tiered prices apply per request.
        per_case = estimate_cost_usd(
            settings.resolved_model, EST_INPUT_TOKENS_PER_CASE, EST_OUTPUT_TOKENS_PER_CASE
        )
        est = None if per_case is None else per_case * len(cases) * args.repeats
        est_text = f"${est:.4f}" if est is not None else "unknown (model not in priced catalog)"
        print(
            f"Planned: {len(cases)} cases x {args.repeats} repeat(s) on {settings.resolved_model}; "
            f"conservative cost estimate {est_text}{' plus judge calls' if args.judge else ''}."
        )
        if not args.allow_paid:
            print("Refusing to call a paid API without --allow-paid.", file=sys.stderr)
            return 2
        if est is None or est > args.max_cost_usd:
            print(
                f"Estimated cost exceeds --max-cost-usd={args.max_cost_usd}; aborting.",
                file=sys.stderr,
            )
            return 2

    try:
        status = create_provider(settings)
    except LLMError as exc:
        print(f"Cannot start: {exc.user_message}", file=sys.stderr)
        return 2
    provider = status.provider
    workspaces = WorkspaceCache(settings)
    results: list[dict] = []
    for repeat in range(args.repeats):
        for case in cases:
            record = run_case(
                case,
                provider,
                workspaces,
                prompt_version=args.prompt_version,
                retriever=retriever,
                judge=args.judge,
            )
            record["repeat"] = repeat
            results.append(record)
            mark = (
                "ERROR" if record.get("error") else ("PASS" if record["score"]["pass"] else "FAIL")
            )
            print(f"[{repeat + 1}/{args.repeats}] {case['id']:<7} {case['category']:<22} {mark}")
            if (record.get("error") or "").split(":", 1)[0] in RUN_STOPPING_ERROR_KINDS:
                print(
                    f"\nStopped at {case['id']}: {record['error']}\nThis error affects every "
                    "case, so the run was stopped and no results file was written.",
                    file=sys.stderr,
                )
                return EXIT_STOPPED

    now = datetime.now(UTC)
    run_id = f"{now:%Y%m%dT%H%M%SZ}_{provider.provider_name}_{provider.model}_{args.prompt_version}".replace(
        "/", "-"
    )
    if args.tag:
        run_id += f"_{args.tag}"
    run = {
        "metadata": {
            "run_id": run_id,
            "timestamp": now.isoformat(timespec="seconds"),
            "provider": provider.provider_name,
            "model": provider.model,
            "offline": provider.is_offline,
            "prompt_version": args.prompt_version,
            "retriever": retriever,
            "dataset_version": dataset["dataset_version"],
            "case_count": len(cases),
            "repeats": args.repeats,
            "judge": args.judge,
            "settings": {
                k: v
                for k, v in settings.model_dump().items()
                if k
                in {
                    "reasoning_effort",
                    "temperature",
                    "top_k",
                    "context_token_budget",
                    "chunk_size",
                    "chunk_overlap",
                    "max_output_tokens",
                    "section_token_budget",
                }
            },
            "git_commit": _git_commit(),
            "versions": _versions(),
        },
        "metrics": scoring.aggregate(results),
        "consistency": scoring.consistency(results),
        "results": results,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    json_path = args.out / f"{run_id}.json"
    json_path.write_text(
        json.dumps(
            run,
            indent=2,
            default=lambda o: asdict(o) if hasattr(o, "__dataclass_fields__") else str(o),
        ),
        encoding="utf-8",
    )
    md_path = args.out / f"{run_id}.md"
    md_path.write_text(render_markdown(run), encoding="utf-8")
    print(f"\nWrote {json_path}\nWrote {md_path}")
    m = run["metrics"]
    print(
        f"overall_pass_rate={m['overall_pass_rate']} answer_accuracy={m['answer_accuracy']} "
        f"correct_abstention_rate={m['correct_abstention_rate']} injection_resistance_rate={m['injection_resistance_rate']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
