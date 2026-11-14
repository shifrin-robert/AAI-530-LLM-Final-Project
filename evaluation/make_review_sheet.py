"""Create a CSV sheet for human review of evaluation outputs.

    # Blank sheet from the labelled cases
    python -m evaluation.make_review_sheet

    # Sheet pre-filled with the answers from a saved run (recommended for live runs)
    python -m evaluation.make_review_sheet evaluation/results/<run_id>.json

Reviewers fill in: correctness (0 wrong / 1 partly / 2 correct), citation_support
(supported / partial / unsupported), usefulness (1-5), reviewer and notes. Automatic scores
never replace this review for cases whose evaluation_method mentions "human".
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
COLUMNS = [
    "case_id",
    "category",
    "task",
    "question_or_focus",
    "criteria",
    "evaluation_method",
    "run_id",
    "model",
    "status",
    "answer_excerpt",
    "auto_pass",
    "correctness_0_2",
    "citation_support",
    "usefulness_1_5",
    "reviewer",
    "notes",
]


def _answer_excerpt(output: dict | None) -> str:
    if not output:
        return ""
    for key in ("answer", "executive_summary", "overview"):
        if key in output:
            return str(output[key])[:600]
    return json.dumps(output)[:600]


def build_rows(run: dict | None) -> list[dict]:
    cases = json.loads((HERE / "test_cases.json").read_text(encoding="utf-8"))["cases"]
    results = {r["case_id"]: r for r in (run or {}).get("results", []) if r.get("repeat", 0) == 0}
    meta = (run or {}).get("metadata", {})
    rows = []
    for case in cases:
        result = results.get(case["id"], {})
        score = result.get("score") or {}
        rows.append(
            {
                "case_id": case["id"],
                "category": case["category"],
                "task": case["task"],
                "question_or_focus": case.get("question")
                or case.get("focus")
                or "(whole document)",
                "criteria": case["criteria"],
                "evaluation_method": case["evaluation_method"],
                "run_id": meta.get("run_id", ""),
                "model": f"{meta.get('provider', '')}:{meta.get('model', '')}" if meta else "",
                "status": score.get("status", ""),
                "answer_excerpt": _answer_excerpt(result.get("output")),
                "auto_pass": score.get("pass", ""),
                "correctness_0_2": "",
                "citation_support": "",
                "usefulness_1_5": "",
                "reviewer": "",
                "notes": "",
            }
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    run = json.loads(Path(args[0]).read_text(encoding="utf-8")) if args else None
    out = HERE / (
        "human_review_template.csv"
        if run is None
        else f"results/{run['metadata']['run_id']}_review.csv"
    )
    rows = build_rows(run)
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {out} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
