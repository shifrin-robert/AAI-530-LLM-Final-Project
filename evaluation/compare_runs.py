"""Compare two evaluation runs (e.g. prompt v1 vs v2, or model A vs model B).

    python -m evaluation.compare_runs evaluation/results/<run_a>.json evaluation/results/<run_b>.json

Prints a metric-by-metric table and the cases whose pass/fail outcome changed (improvements
and regressions). The runs should use the same dataset version and cases; the script warns
when they do not.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

METRICS = (
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
    "latency_mean_s",
    "input_tokens",
    "output_tokens",
    "cost_usd",
)


def compare(a: dict, b: dict) -> str:
    ma, mb = a["metadata"], b["metadata"]
    lines = [f"# Run comparison: `{ma['run_id']}` (A) vs `{mb['run_id']}` (B)", ""]
    for key in (
        "provider",
        "model",
        "prompt_version",
        "retriever",
        "dataset_version",
        "case_count",
        "repeats",
    ):
        lines.append(f"- {key}: A={ma.get(key)} | B={mb.get(key)}")
    if ma.get("dataset_version") != mb.get("dataset_version") or ma.get("case_count") != mb.get(
        "case_count"
    ):
        lines.append(
            "\n**Warning:** the runs used different datasets or case counts; differences are not comparable."
        )
    lines += ["", "| Metric | A | B | B - A |", "|---|---|---|---|"]
    for key in METRICS:
        va, vb = a["metrics"].get(key), b["metrics"].get(key)
        delta = (
            round(vb - va, 3)
            if isinstance(va, int | float) and isinstance(vb, int | float)
            else "n/a"
        )
        lines.append(f"| {key} | {va} | {vb} | {delta} |")
    outcome_a = {
        r["case_id"]: bool((r.get("score") or {}).get("pass"))
        for r in a["results"]
        if r.get("repeat", 0) == 0
    }
    outcome_b = {
        r["case_id"]: bool((r.get("score") or {}).get("pass"))
        for r in b["results"]
        if r.get("repeat", 0) == 0
    }
    improved = sorted(c for c in outcome_a if c in outcome_b and not outcome_a[c] and outcome_b[c])
    regressed = sorted(c for c in outcome_a if c in outcome_b and outcome_a[c] and not outcome_b[c])
    lines += [
        "",
        f"Improved in B: {', '.join(improved) or 'none'}",
        f"Regressed in B: {', '.join(regressed) or 'none'}",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 2:
        print(__doc__)
        return 2
    a, b = (json.loads(Path(p).read_text(encoding="utf-8")) for p in args)
    print(compare(a, b))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
