"""Estimate the cost of 100 typical DocIntel requests for every model in the priced catalog.

    python scripts/estimate_costs.py

The workload assumptions are stated below and reproduced in docs/API_SELECTION_REPORT.md.
Token counts are planning estimates (about 4 characters per token), not measurements; prices
are the providers' standard (non-batch) list prices checked on the date in model_catalog.py.
No prompt caching or batch discounts are assumed.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from docintel.model_catalog import CATALOG, VERIFIED_ON

# (label, requests out of 100, input tokens per request, output tokens per request incl. reasoning)
WORKLOAD = [
    ("Grounded Q&A (v2 prompt ~1.3k + 8 passages ~2.1k + question/schema ~0.6k)", 70, 4_000, 800),
    ("Summary of a ~20-page document (2 map calls + 1 reduce call)", 15, 17_400, 3_600),
    ("Extraction from a ~20-page document (2 section calls)", 10, 14_000, 3_000),
    ("Comparison of two documents (1 call)", 5, 10_000, 1_500),
]


def totals() -> tuple[int, int]:
    total_in = sum(n * tin for _, n, tin, _ in WORKLOAD)
    total_out = sum(n * tout for _, n, _, tout in WORKLOAD)
    return total_in, total_out


def table() -> str:
    total_in, total_out = totals()
    lines = [
        f"Workload per 100 requests: {total_in:,} input tokens and {total_out:,} output tokens "
        f"(prices checked {VERIFIED_ON}).",
        "",
        "| Provider | Model | Tier | Input $/1M | Output $/1M | Cost per 100 requests | Cost per request |",
        "|---|---|---|---|---|---|---|",
    ]
    rows = []
    for info in CATALOG:
        # Every individual request is far below Haiku 5.5's 100k-token long-prompt threshold, so
        # compute per request type rather than on the aggregate token count.
        cost = sum(n * info.estimate_cost(tin, tout) for _, n, tin, tout in WORKLOAD)
        rows.append((cost, info))
    for cost, info in sorted(rows, key=lambda r: r[0]):
        lines.append(
            f"| {info.provider} | `{info.model_id}` | {info.tier} | ${info.input_per_mtok:g} | "
            f"${info.output_per_mtok:g} | ${cost:.2f} | ${cost / 100:.4f} |"
        )
    return "\n".join(lines)


def main() -> int:
    print("Workload assumptions:")
    for label, n, tin, tout in WORKLOAD:
        print(f"- {n} x {label}: {tin:,} input / {tout:,} output tokens each")
    print()
    print(table())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
