"""Create the human-review worksheet (CSV) for the 40 evaluation cases.

    # Blank template (no run), written to evaluation/human_review_template.csv
    python -m evaluation.make_review_sheet

    # Worksheet pre-filled with a saved run's answers, written to evaluation/human_review/
    python -m evaluation.make_review_sheet evaluation/results/<run>.json

    # ...plus the pass/fail outcome of every repeat from a repeated run of the same prompt
    python -m evaluation.make_review_sheet evaluation/results/<run>.json --repeats evaluation/results/<run_x3>.json

The automatic columns are copied from the saved run files, which are only read. The reviewer
columns (correctness, citation support, usefulness, notes, reviewer, review date) are always left blank:
only a person who has reviewed the case fills them in. See evaluation/human_review/README.md.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE_PATH = HERE / "human_review_template.csv"
REVIEW_DIR = HERE / "human_review"

REVIEWER_COLUMNS = [
    "Human correctness judgment",
    "Citation-support judgment",
    "Usefulness (1-5)",
    "Notes",
    "Reviewer",
    "Review date",
]
COLUMNS = [
    "Test ID",
    "Category",
    "Task",
    "User question",
    "Expected answer",
    "Expected source pages",
    "Response status",
    "Actual response",
    "Source references",
    "Automatic citation checks",
    "Automatic score",
    "Automatic outcome in repeated run",
    "What to check",
    "Run ID",
    *REVIEWER_COLUMNS,
]


def _items(title: str, entries: list[str]) -> list[str]:
    return [f"{title}:", *(f"- {e}" for e in entries)] if entries else []


def response_text(task: str, output: dict | None) -> str:
    """The whole response in readable form, so the reviewer sees what the scorer saw."""
    if not output:
        return ""
    if task == "qa":
        lines = [output.get("answer", "")]
        lines += _items(
            "Conflicts listed",
            [f"{c.get('nature')}: {c.get('description')}" for c in output.get("conflicts", [])],
        )
        lines += _items("Missing information", list(output.get("missing_information", [])))
        return "\n".join(lines)
    if task == "summary":
        lines = [f"Executive summary: {output.get('executive_summary', '')}"]
        if output.get("detailed_summary"):
            lines.append(f"Detailed summary: {output['detailed_summary']}")
        for key, title in (
            ("key_findings", "Key findings"),
            ("action_items", "Action items"),
            ("obligations", "Obligations"),
            ("risks_and_concerns", "Risks and concerns"),
        ):
            lines += _items(title, [p.get("text", "") for p in output.get(key, [])])
        lines += _items(
            "Important dates",
            [f"{d.get('date')}: {d.get('description')}" for d in output.get("important_dates", [])],
        )
        lines += _items("Gaps or limitations", list(output.get("gaps_or_limitations", [])))
        return "\n".join(lines)
    if task == "extraction":
        lines = []
        for key, values in output.items():
            if key == "not_found" or not isinstance(values, list):
                continue
            lines += _items(
                key.replace("_", " ").capitalize(),
                [
                    item.get("value", "") + (f" ({item['detail']})" if item.get("detail") else "")
                    for item in values
                ],
            )
        lines += _items("Not found", list(output.get("not_found", [])))
        return "\n".join(lines)
    if task == "comparison":
        lines = [f"Overview: {output.get('overview', '')}"]
        lines += _items(
            "Findings",
            [
                f"{f.get('topic')} ({f.get('nature')}): {f.get('description')}"
                for f in output.get("findings", [])
            ],
        )
        if output.get("limitations"):
            lines.append(f"Limitations: {output['limitations']}")
        return "\n".join(lines)
    return json.dumps(output, ensure_ascii=False)


def score_text(task: str, score: dict | None, error: str | None = None) -> str:
    """PASS or FAIL with the automatic checks that failed, in words."""
    if error:
        return f"ERROR: {error}"
    if not score:
        return ""
    reasons = []
    if task == "qa" and not score.get("status_ok", True):
        reasons.append(f"status {score.get('status')} not accepted")
    if score.get("missing_facts"):
        reasons.append("missing " + ", ".join(group[0] for group in score["missing_facts"]))
    if task == "extraction":
        reasons.append(f"recall {score.get('recall')}")
    if score.get("forbidden_hits"):
        reasons.append("forbidden phrase " + ", ".join(score["forbidden_hits"]))
    if score.get("fabricated_ids"):
        reasons.append("unknown source IDs " + ", ".join(score["fabricated_ids"]))
    if score.get("canary_leak"):
        reasons.append("prompt canary leaked")
    if score.get("amendment_not_contradiction_ok") is False:
        reasons.append("amendment reported as a contradiction")
    verdict = "PASS" if score.get("pass") else "FAIL"
    return f"{verdict} ({'; '.join(reasons)})" if reasons else verdict


def citation_text(grounding: dict | None) -> str:
    if not grounding:
        return ""
    return (
        f"IDs valid {grounding.get('valid_citations', 0)}/{grounding.get('total_citations', 0)}; "
        f"quotes found {grounding.get('quotes_found', 0)}/{grounding.get('quotes_checked', 0)}; "
        f"heuristic support {grounding.get('likely_supported', 0)}/{grounding.get('assessed', 0)} "
        "(word overlap, not a semantic check)"
    )


def _expected_pages(case: dict) -> str:
    evidence = case["expected"].get("evidence") or []
    if evidence:
        return "; ".join(f"{e['document']} p{e['page']}" for e in evidence)
    return "; ".join(case["documents"]) + " (whole document)"


def build_rows(run: dict | None, repeats: dict | None = None) -> list[dict]:
    cases = json.loads((HERE / "test_cases.json").read_text(encoding="utf-8"))["cases"]
    first = {r["case_id"]: r for r in (run or {}).get("results", []) if r.get("repeat", 0) == 0}
    outcomes: dict[str, list[str]] = {}
    for r in sorted((repeats or {}).get("results", []), key=lambda r: r.get("repeat", 0)):
        outcome = (
            "ERROR"
            if r.get("error")
            else ("PASS" if (r.get("score") or {}).get("pass") else "FAIL")
        )
        outcomes.setdefault(r["case_id"], []).append(outcome)
    run_id = (run or {}).get("metadata", {}).get("run_id", "")
    rows = []
    for case in cases:
        result = first.get(case["id"], {})
        task = case["task"]
        row = {
            "Test ID": case["id"],
            "Category": case["category"],
            "Task": task,
            "User question": case.get("question")
            or (f"Focus: {case['focus']}" if case.get("focus") else "(whole document)"),
            "Expected answer": case["criteria"],
            "Expected source pages": _expected_pages(case),
            "Response status": (result.get("output") or {}).get("status", ""),
            "Actual response": response_text(task, result.get("output")),
            "Source references": "; ".join(result.get("cited_pages") or []),
            "Automatic citation checks": citation_text(result.get("grounding")),
            "Automatic score": score_text(task, result.get("score"), result.get("error")),
            "Automatic outcome in repeated run": ", ".join(outcomes.get(case["id"], [])),
            "What to check": case["evaluation_method"],
            "Run ID": run_id if result else "",
        }
        row.update({column: "" for column in REVIEWER_COLUMNS})
        rows.append(row)
    return rows


def write_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig so that Excel shows curly quotes and dashes correctly
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create the human-review worksheet.")
    parser.add_argument("run", nargs="?", type=Path, help="saved run to pre-fill from")
    parser.add_argument("--repeats", type=Path, help="repeated run of the same prompt")
    parser.add_argument("--out", type=Path, help="output CSV path")
    args = parser.parse_args(argv)
    run = json.loads(args.run.read_text(encoding="utf-8")) if args.run else None
    repeats = json.loads(args.repeats.read_text(encoding="utf-8")) if args.repeats else None
    if args.out:
        out = args.out
    elif run is None:
        out = TEMPLATE_PATH
    else:
        out = REVIEW_DIR / f"{run['metadata']['run_id']}_human_review.csv"
    rows = build_rows(run, repeats)
    write_rows(out, rows)
    print(f"Wrote {out} ({len(rows)} rows; reviewer columns left blank)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
