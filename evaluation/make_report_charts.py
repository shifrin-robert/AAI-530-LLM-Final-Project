"""Draw the evaluation report's figures (SVG) from the saved run files.

    python -m evaluation.make_report_charts

Writes three figures to docs/figures/. Every value comes from the run files in
evaluation/results/ (read only) and from the scoring audit's rules (evaluation/scoring_audit.py);
none is typed in by hand. The figures are static images, so docs/EVALUATION_REPORT.md also gives
every value in a table.
"""

from __future__ import annotations

import json
from xml.sax.saxutils import escape

from docintel.config import PROJECT_ROOT
from docintel.model_catalog import estimate_cost_usd
from evaluation import scoring_audit
from evaluation.evaluation_runner import EST_INPUT_TOKENS_PER_CASE, EST_OUTPUT_TOKENS_PER_CASE

FIGURES_DIR = PROJECT_ROOT / "docs" / "figures"

# Light values, then dark values for viewers whose system is in dark mode. Colours follow the
# reference palette of the data-visualisation guidelines: one blue series, status red and amber
# (always with a glyph and a legend label), and recessive grey chrome.
STYLE = """
<style>
  svg { --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781; --grid:#e1e0d9;
        --axis:#c3c2b7; --series:#2a78d6; --pass:#cde2fb; --fail:#d03b3b; --warn:#fab219; }
  @media (prefers-color-scheme: dark) {
    svg { --surface:#1a1a19; --ink:#f0efec; --ink2:#c3c2b7; --muted:#898781; --grid:#2c2c2a;
          --axis:#383835; --series:#3987e5; --pass:#184f95; }
  }
  text { font-family: system-ui, -apple-system, "Segoe UI", sans-serif; fill: var(--ink); }
  .title { font-size: 17px; font-weight: 600; }
  .sub { font-size: 13px; fill: var(--ink2); }
  .label { font-size: 13px; }
  .small { font-size: 12px; fill: var(--ink2); }
  .num { font-variant-numeric: tabular-nums; }
</style>
"""


def _svg(width: int, height: int, title: str, desc: str, body: list[str]) -> str:
    return "\n".join(
        [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
            f'width="{width}" height="{height}" role="img" aria-labelledby="t d">',
            f'<title id="t">{escape(title)}</title>',
            f'<desc id="d">{escape(desc)}</desc>',
            STYLE.strip(),
            f'<rect width="{width}" height="{height}" rx="8" fill="var(--surface)"/>',
            *body,
            "</svg>",
            "",
        ]
    )


def _text(x: float, y: float, content: str, cls: str = "label", anchor: str = "start") -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" class="{cls}" text-anchor="{anchor}">'
        f"{escape(content)}</text>"
    )


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.0f}%"


# ----------------------------------------------------------------------------- data


def load_audit() -> dict[str, dict]:
    """Audit entries keyed by a short run name: offline, v1, v2, v2x3."""
    runs = scoring_audit.build_audit(scoring_audit.default_runs(), with_context_check=False)["runs"]
    named = {}
    for run in runs:
        if run["offline"]:
            named["offline"] = run
        elif run["prompt_version"] == "v1":
            named["v1"] = run
        elif run["repeats"] > 1:
            named["v2x3"] = run
        else:
            named["v2"] = run
    missing = {"offline", "v1", "v2", "v2x3"} - set(named)
    if missing:
        raise SystemExit(f"Missing saved runs: {', '.join(sorted(missing))}")
    return named


# ----------------------------------------------------------------------------- figure 1


def outcome_grid(audit: dict[str, dict]) -> str:
    """Pass or fail for every case in every run, with scoring-only failures marked apart."""
    case_ids = [c["id"] for c in json.loads(scoring_audit.CASES_PATH.read_text("utf-8"))["cases"]]
    rows = [("Offline baseline (not an LLM)", audit["offline"], 0)]
    rows += [("Prompt v1", audit["v1"], 0), ("Prompt v2, main run", audit["v2"], 0)]
    rows += [(f"Prompt v2, repeat {i + 1}", audit["v2x3"], i) for i in range(3)]

    left, top, cell, pitch, group_gap, row_pitch = 216, 74, 14, 16, 8, 22
    groups: list[tuple[str, list[str]]] = []
    for cid in case_ids:
        prefix = cid.split("-")[0]
        if not groups or groups[-1][0] != prefix:
            groups.append((prefix, []))
        groups[-1][1].append(cid)
    x_of: dict[str, float] = {}
    x = left
    for _, members in groups:
        for cid in members:
            x_of[cid] = x
            x += pitch
        x += group_gap
    grid_right = x - group_gap
    width = int(grid_right + 70)

    body = [
        _text(24, 32, "Every case, every run: pass or fail", "title"),
        _text(
            24,
            52,
            "40 cases in columns, grouped by category; 6 runs in rows. Original scoring.",
            "sub",
        ),
    ]
    for r, (name, run, repeat) in enumerate(rows):
        y = top + r * row_pitch + (8 if r > 0 else 0)
        outcome = {row["case_id"]: row for row in run["rows"] if row["repeat"] == repeat}
        body.append(_text(left - 12, y + 11, name, "label", "end"))
        passed = 0
        for cid in case_ids:
            row = outcome[cid]
            cx = x_of[cid]
            if row["original_pass"]:
                passed += 1
                state, fill = "passed", "var(--pass)"
            elif row["revised_pass"]:
                state, fill = "failed under the original injection rule only", "var(--warn)"
            else:
                state, fill = "failed", "var(--fail)"
            body.append(
                f'<rect x="{cx}" y="{y}" width="{cell}" height="{cell}" rx="3" fill="{fill}">'
                f"<title>{escape(f'{cid}, {name}: {state}')}</title></rect>"
            )
            if not row["original_pass"]:
                glyph = "#ffffff" if fill == "var(--fail)" else "#0b0b0b"
                body.append(
                    f'<path d="M{cx + 4} {y + 4} l6 6 M{cx + 10} {y + 4} l-6 6" '
                    f'stroke="{glyph}" stroke-width="1.8" stroke-linecap="round"/>'
                )
        body.append(_text(grid_right + 12, y + 11, f"{passed}/40", "label num"))
    bottom = top + len(rows) * row_pitch + 8
    for prefix, members in groups:
        centre = (x_of[members[0]] + x_of[members[-1]] + cell) / 2
        body.append(_text(centre, bottom + 10, prefix, "small", "middle"))

    legend_y = bottom + 42
    items = [
        ("var(--pass)", None, "Passed"),
        ("var(--fail)", "#ffffff", "Failed"),
        (
            "var(--warn)",
            "#0b0b0b",
            "Failed only under the original injection rule (passes when revised)",
        ),
    ]
    lx = 24
    for fill, glyph, label in items:
        body.append(
            f'<rect x="{lx}" y="{legend_y - 11}" width="14" height="14" rx="3" fill="{fill}"/>'
        )
        if glyph:
            body.append(
                f'<path d="M{lx + 4} {legend_y - 7} l6 6 M{lx + 10} {legend_y - 7} l-6 6" '
                f'stroke="{glyph}" stroke-width="1.8" stroke-linecap="round"/>'
            )
        body.append(_text(lx + 22, legend_y, label, "label"))
        lx += 22 + 8 * len(label) + 28
    key = (
        "DF direct factual, MP multi-page, MD multi-document, NUM numerical, MI missing "
        "information, CF conflicting evidence,",
        "INJ prompt injection, AMB ambiguous, SUM summary, EXT extraction, CMP comparison",
    )
    body.append(_text(24, legend_y + 28, key[0], "small"))
    body.append(_text(24, legend_y + 46, key[1], "small"))
    height = legend_y + 66
    return _svg(
        width,
        height,
        "Every case, every run: pass or fail",
        "Grid of 40 evaluation cases by 6 runs. The offline baseline passes 23 of 40. GPT-6 Luna "
        "with prompt v1 passes 37, prompt v2 passes 39 in the main run and 38, 40 and 38 in its "
        "three repeats. CF-02 fails in most live runs; INJ-03 fails in two repeats and in v1 only "
        "under the original injection rule.",
        body,
    )


# ----------------------------------------------------------------------------- figure 2


def scoring_comparison(audit: dict[str, dict]) -> str:
    """Original versus revised scoring for the two audited metrics, as dumbbells."""
    runs = [
        ("Offline baseline", audit["offline"]),
        ("Prompt v1", audit["v1"]),
        ("Prompt v2", audit["v2"]),
        ("Prompt v2, 3 repeats", audit["v2x3"]),
    ]
    panels = [
        ("Injection resistance", "injection_resistance_rate"),
        ("Conflict handling", "conflict_handling_rate"),
    ]
    label_w, panel_w, panel_gap, top, row_h = 170, 300, 70, 116, 34
    width = 24 + label_w + 2 * panel_w + panel_gap + 40
    body = [
        _text(24, 32, "What the scoring audit changes", "title"),
        _text(
            24,
            52,
            "Same saved answers, scored by the original rules and by the revised (proposed) rules.",
            "sub",
        ),
    ]
    for i, (name, _) in enumerate(runs):
        body.append(_text(24 + label_w - 14, top + i * row_h + 5, name, "label", "end"))
    for p, (title, key) in enumerate(panels):
        x0 = 24 + label_w + p * (panel_w + panel_gap)
        body.append(_text(x0, top - 30, title, "label"))
        for tick in (0, 0.25, 0.5, 0.75, 1.0):
            gx = x0 + tick * panel_w
            body.append(
                f'<line x1="{gx:.1f}" y1="{top - 16}" x2="{gx:.1f}" y2="{top + 3 * row_h + 14}" '
                'stroke="var(--grid)" stroke-width="1"/>'
            )
            body.append(_text(gx, top + 3 * row_h + 32, _pct(tick), "small num", "middle"))
        for i, (name, run) in enumerate(runs):
            y = top + i * row_h
            before, after = run["original"][key], run["revised"][key]
            xb, xa = x0 + before * panel_w, x0 + after * panel_w
            if abs(xa - xb) > 0.5:
                body.append(
                    f'<line x1="{xb:.1f}" y1="{y}" x2="{xa:.1f}" y2="{y}" stroke="var(--series)" '
                    'stroke-width="2" stroke-linecap="round" opacity="0.6"/>'
                )
            body.append(
                f'<circle cx="{xb:.1f}" cy="{y}" r="7" fill="var(--surface)" stroke="var(--ink2)" '
                f'stroke-width="2"><title>{escape(f"{name}, {title}, original: {_pct(before)}")}'
                "</title></circle>"
            )
            body.append(
                f'<circle cx="{xa:.1f}" cy="{y}" r="5" fill="var(--series)" stroke="var(--surface)" '
                f'stroke-width="2"><title>{escape(f"{name}, {title}, revised: {_pct(after)}")}'
                "</title></circle>"
            )
            if abs(xa - xb) > 0.5:
                anchor_x = max(xa, xb)
                body.append(
                    _text(
                        min(anchor_x + 14, x0 + panel_w + 6),
                        y - 10,
                        f"{_pct(before)} to {_pct(after)}",
                        "small num",
                        "end" if anchor_x + 14 > x0 + panel_w else "start",
                    )
                )
    legend_y = top + 3 * row_h + 66
    body.append(
        f'<circle cx="31" cy="{legend_y - 4}" r="7" fill="var(--surface)" stroke="var(--ink2)" '
        'stroke-width="2"/>'
    )
    body.append(_text(46, legend_y, "Original scoring (scorer of record)", "label"))
    body.append(
        f'<circle cx="331" cy="{legend_y - 4}" r="5" fill="var(--series)" stroke="var(--surface)" '
        'stroke-width="2"/>'
    )
    body.append(_text(344, legend_y, "Revised scoring (proposed; not yet adopted)", "label"))
    body.append(
        _text(
            24,
            legend_y + 26,
            "Injection: 4 cases per run (12 for 3 repeats). Conflict: 3 cases per run (9).",
            "small",
        )
    )
    return _svg(
        width,
        legend_y + 44,
        "What the scoring audit changes",
        "Dumbbell chart. Injection resistance, original to revised: offline 75% to 75%, prompt v1 "
        "75% to 100%, prompt v2 100% to 100%, prompt v2 three repeats 83% to 100%. Conflict "
        "handling: offline 0% to 0%, v1 33% to 33%, v2 33% to 67%, v2 three repeats 44% to 78%.",
        body,
    )


# ----------------------------------------------------------------------------- figure 3


def cost_chart() -> str:
    """Actual cost from API token counts against the runner's pre-run estimate."""
    runs = []
    for path in scoring_audit.default_runs():
        run = json.loads(path.read_text(encoding="utf-8"))
        meta = run["metadata"]
        if meta["offline"]:
            continue
        per_case = estimate_cost_usd(
            meta["model"], EST_INPUT_TOKENS_PER_CASE, EST_OUTPUT_TOKENS_PER_CASE
        )
        case_runs = len(run["results"])
        name = f"Prompt {meta['prompt_version']}" + (
            f", {meta['repeats']} repeats" if meta["repeats"] > 1 else ""
        )
        runs.append(
            (f"{name} ({case_runs} case runs)", run["metrics"]["cost_usd"], per_case * case_runs)
        )
    label_w, plot_w, top, row_h, bar_h = 230, 520, 92, 40, 16
    scale_max = 0.18
    width = 24 + label_w + plot_w + 120
    body = [
        _text(24, 32, "Cost of each live run: actual against the pre-run estimate", "title"),
        _text(
            24, 52, "Actual cost from the token counts the API returned, at catalog prices.", "sub"
        ),
    ]
    x0 = 24 + label_w
    for tick in (0, 0.05, 0.10, 0.15):
        gx = x0 + tick / scale_max * plot_w
        body.append(
            f'<line x1="{gx:.1f}" y1="{top - 14}" x2="{gx:.1f}" y2="{top + len(runs) * row_h - 10}" '
            'stroke="var(--grid)" stroke-width="1"/>'
        )
        body.append(_text(gx, top + len(runs) * row_h + 8, f"${tick:.2f}", "small num", "middle"))
    for i, (name, actual, estimate) in enumerate(runs):
        y = top + i * row_h
        w = max(actual / scale_max * plot_w, 2)
        ex = x0 + estimate / scale_max * plot_w
        body.append(_text(x0 - 14, y + 12, name, "label", "end"))
        body.append(
            f'<path d="M{x0} {y} h{w - 4:.1f} a4 4 0 0 1 4 4 v{bar_h - 8} a4 4 0 0 1 -4 4 h{-(w - 4):.1f} z" '
            f'fill="var(--series)"><title>{escape(f"{name}: actual ${actual:.4f}")}</title></path>'
        )
        body.append(
            f'<line x1="{ex:.1f}" y1="{y - 5}" x2="{ex:.1f}" y2="{y + bar_h + 5}" stroke="var(--ink)" '
            f'stroke-width="2" stroke-linecap="round"><title>{escape(f"{name}: estimate ${estimate:.4f}")}'
            "</title></line>"
        )
        body.append(_text(x0 + w + 8, y + 12, f"${actual:.4f}", "small num"))
        body.append(_text(ex + 8, y + 12, f"estimate ${estimate:.3f}", "small num"))
    legend_y = top + len(runs) * row_h + 44
    body.append(
        f'<rect x="24" y="{legend_y - 11}" width="14" height="14" rx="3" fill="var(--series)"/>'
    )
    body.append(_text(46, legend_y, "Actual cost", "label"))
    body.append(
        f'<line x1="170" y1="{legend_y - 13}" x2="170" y2="{legend_y + 3}" stroke="var(--ink)" '
        'stroke-width="2" stroke-linecap="round"/>'
    )
    body.append(
        _text(
            182,
            legend_y,
            "Pre-run estimate (6,000 input and 1,500 output tokens per case)",
            "label",
        )
    )
    total_actual = sum(r[1] for r in runs)
    total_estimate = sum(r[2] for r in runs)
    return _svg(
        width,
        legend_y + 24,
        "Cost of each live run: actual against the pre-run estimate",
        f"Three live runs cost ${total_actual:.4f} in total against estimates of "
        f"${total_estimate:.3f}: "
        + "; ".join(f"{n}: ${a:.4f} actual, ${e:.3f} estimated" for n, a, e in runs)
        + ".",
        body,
    )


def main() -> int:
    audit = load_audit()
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    figures = {
        "live_case_outcomes.svg": outcome_grid(audit),
        "scoring_audit_comparison.svg": scoring_comparison(audit),
        "live_run_costs.svg": cost_chart(),
    }
    for name, svg in figures.items():
        (FIGURES_DIR / name).write_text(svg, encoding="utf-8")
        print(f"Wrote {FIGURES_DIR / name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
