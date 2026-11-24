"""Generate the synthetic PDFs for the generalization set (evaluation/generalization/).

    python -m evaluation.build_generalization_fixtures

The generalization set is separate from the 40-case benchmark. It tests whether a prompt handles
financial figures that differ across documents for different reasons: reported as of different
dates, current against historical, revised against original, compatible, or genuinely
contradictory. The documents use new fictional organizations and figures that appear neither in
the benchmark fixtures nor in any prompt. The cases and their reference answers were written on
2026-11-15, before any model was run on them.

The PDFs are written to evaluation/fixtures/generalization/. The benchmark fixtures in
evaluation/fixtures/ are not touched. The same renderer as the benchmark is used, so the output is
deterministic and every fact sits on a fixed page.
"""

from __future__ import annotations

from pathlib import Path

from evaluation.build_fixtures import FIXTURES_DIR, build_text_pdf

GENERALIZATION_FIXTURES_DIR = FIXTURES_DIR / "generalization"

DOCUMENTS: dict[str, dict] = {
    # ------------------------------------------------------------------------------------------
    "meadowbrook_renovation_report_q1_2026.pdf": {
        "title": "Clinic Renovation Progress Report: Meadowbrook Community Health Center (Q1 2026)",
        "pages": [
            """
<h1>Clinic Renovation Progress Report</h1>
<p class="meta"><b>Organization:</b> Meadowbrook Community Health Center<br/>
<b>Reporting period:</b> January 1 to March 31, 2026<br/>
<b>Prepared by:</b> Dana Whitcombe, Facilities Director<br/>
<b>Report date:</b> April 8, 2026</p>
<h2>Progress</h2>
<p>Construction of the new east wing is 40% complete. The general contractor is Halvorsen
Builders Inc. Substantial completion is scheduled for September 30, 2026.</p>
<h2>Budget and spending</h2>
<p>The board approved a renovation budget of $1,150,000 on January 12, 2026. Spending to date is
$640,000 as of March 31, 2026.</p>
""",
            """
<h2>Funding</h2>
<p>The state capital grant awarded on February 2, 2026 is $300,000. The remainder of the
renovation cost is funded from the Center's capital reserve.</p>
<h2>Risks</h2>
<p>Delivery of the new air-handling units may slip by two weeks. Owner: Dana Whitcombe.</p>
""",
        ],
    },
    # ------------------------------------------------------------------------------------------
    "meadowbrook_board_memo_may_2026.pdf": {
        "title": "Board Memo: Meadowbrook clinic renovation spending and budget revision",
        "pages": [
            """
<h1>Memorandum</h1>
<p class="meta"><b>To:</b> Board of Directors, Meadowbrook Community Health Center<br/>
<b>From:</b> Ruth Abernathy, Chief Financial Officer<br/>
<b>Date:</b> May 20, 2026<br/>
<b>Subject:</b> Clinic renovation: spending and budget revision</p>
<h2>Spending</h2>
<p>Spending to date on the clinic renovation is $702,500 as of May 15, 2026.</p>
<h2>Budget Revision No. 1</h2>
<p>On May 18, 2026 the board approved Budget Revision No. 1, which raises the renovation budget
to $1,240,000. The revised budget replaces the budget of $1,150,000 approved on January 12,
2026. The increase pays for upgraded air-handling units.</p>
""",
            """
<h2>Funding</h2>
<p>The state capital grant awarded on February 2, 2026 is $350,000. The remainder of the
renovation cost is funded from the Center's capital reserve.</p>
<h2>Next report</h2>
<p>The Facilities Director will report progress to the board in July 2026.</p>
""",
        ],
    },
    # ------------------------------------------------------------------------------------------
    "pinecrest_food_services_summary_fy2026.pdf": {
        "title": "Food Services Annual Summary FY2026: Pinecrest Unified School District",
        "pages": [
            """
<h1>Food Services Annual Summary, Fiscal Year 2026</h1>
<p class="meta"><b>District:</b> Pinecrest Unified School District<br/>
<b>Prepared by:</b> Luis Ferreira, Director of Food Services<br/>
<b>Date:</b> July 15, 2026</p>
<h2>Reserve fund</h2>
<p>The food services reserve fund balance is $2.4 million as of June 30, 2026, compared with
$1.9 million as of June 30, 2025.</p>
<h2>Meals served</h2>
<p>The district served 1,312,000 meals in fiscal year 2026, 4% more than in fiscal year 2025.</p>
""",
            """
<h2>Technology vendor</h2>
<p>The district's meal-service technology vendor is Tallgrass Software. The annual cost of the
Tallgrass service in fiscal year 2026 was $48,000.</p>
<h2>Fiscal year 2027 budget</h2>
<p>On June 10, 2026 the board adopted a fiscal year 2027 food services budget of $3,050,000.</p>
""",
        ],
    },
    # ------------------------------------------------------------------------------------------
    "pinecrest_board_update_aug_2026.pdf": {
        "title": "Board Update: Pinecrest Unified School District food services (August 2026)",
        "pages": [
            """
<h1>Board Update: Food Services</h1>
<p class="meta"><b>District:</b> Pinecrest Unified School District<br/>
<b>From:</b> Office of the Chief Business Official<br/>
<b>Date:</b> August 28, 2026</p>
<h2>Amended fiscal year 2027 budget</h2>
<p>On August 26, 2026 the board adopted an amended fiscal year 2027 food services budget of
$3,180,000. The amended budget supersedes the budget adopted on June 10, 2026.</p>
<h2>Technology vendor agreement</h2>
<p>Under its agreement with Tallgrass Software, the district pays a monthly fee of $4,000 for the
meal-service technology platform.</p>
""",
        ],
    },
    # ------------------------------------------------------------------------------------------
    "harlow_arts_council_audited_statement_2025.pdf": {
        "title": "Audited Financial Statement 2025: Harlow Arts Council",
        "pages": [
            """
<h1>Audited Financial Statement</h1>
<p class="meta"><b>Organization:</b> Harlow Arts Council<br/>
<b>Period:</b> year ended December 31, 2025<br/>
<b>Auditor:</b> Penrose &amp; Tate LLP; opinion dated March 4, 2026</p>
<h2>Statement of activities</h2>
<table>
<tr><th>Item</th><th>Amount</th></tr>
<tr><td>Total revenue</td><td>$2,180,000</td></tr>
<tr><td>Total expenses</td><td>$1,870,000</td></tr>
<tr><td>Operating surplus</td><td>$310,000</td></tr>
</table>
""",
            """
<h2>Note 6: Gallery refurbishment</h2>
<p>As of December 31, 2025, the Council had spent $61,750 on the gallery refurbishment project,
which began in October 2025.</p>
<h2>Note 7: Restricted funds</h2>
<p>Restricted funds held for the youth music program totalled $95,000 at year end.</p>
""",
        ],
    },
    # ------------------------------------------------------------------------------------------
    "harlow_arts_council_chair_letter_2026.pdf": {
        "title": "Letter from the Chair: Harlow Arts Council (April 2026)",
        "pages": [
            """
<h1>Letter from the Chair</h1>
<p class="meta"><b>From:</b> Miriam Osei, Chair, Harlow Arts Council<br/>
<b>To:</b> Members and supporters<br/>
<b>Date:</b> April 2, 2026</p>
<p>Dear members and supporters,</p>
<p>2025 was a year of growth for the Council. Our revenue reached $2.18 million, the highest in
the Council's history.</p>
<p>The Council recorded an operating deficit of $45,000 for the year ended December 31, 2025.</p>
""",
            """
<h2>Gallery refurbishment</h2>
<p>Spending on the gallery refurbishment reached $86,300 as of February 28, 2026. The gallery will
reopen in June 2026.</p>
<h2>Endowment</h2>
<p>The endowment was valued at $3.6 million as of March 31, 2026, compared with $3.1 million as of
March 31, 2025.</p>
""",
        ],
    },
}


def build_all(out_dir: Path = GENERALIZATION_FIXTURES_DIR) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, spec in DOCUMENTS.items():
        path = out_dir / name
        path.write_bytes(build_text_pdf(spec))
        written.append(path)
    return written


if __name__ == "__main__":
    for path in build_all():
        print(f"wrote {path}")
