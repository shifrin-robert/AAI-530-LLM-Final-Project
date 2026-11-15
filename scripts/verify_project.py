"""One-command project audit: lint, formatting, tests, secrets, repository hygiene.

    python scripts/verify_project.py

Exits non-zero if any check fails. All checks run offline; no API calls are made.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable

REQUIRED_FILES = [
    "app.py",
    "pyproject.toml",
    "requirements-lock.txt",
    "README.md",
    ".gitignore",
    ".env.example",
    "src/docintel/config.py",
    "src/docintel/llm_client.py",
    "src/docintel/grounding.py",
    "prompts/grounded_qa_v1.md",
    "prompts/grounded_qa_v2.md",
    "prompts/grounded_qa_v3.md",
    "evaluation/test_cases.json",
    "evaluation/evaluation_runner.py",
    "evaluation/scoring_audit.py",
    "evaluation/source_relationships.json",
    "evaluation/human_review_template.csv",
    "evaluation/human_review/README.md",
    "docs/API_SELECTION_REPORT.md",
    "docs/PROJECT_DOCUMENTATION.md",
    "docs/ARCHITECTURE.md",
    "docs/PROMPT_AND_TESTING_APPENDIX.md",
    "docs/AI_USE_AND_ETHICAL_REFLECTION.md",
    "docs/EVALUATION_REPORT.md",
    "docs/USER_GUIDE.md",
    "docs/PRESENTATION_SCRIPT.md",
    "docs/DEMO_WALKTHROUGH.md",
    "docs/REQUIREMENTS_TRACEABILITY.md",
    "docs/TEAM_CONTRIBUTIONS.md",
    "docs/LIVE_EVALUATION_GUIDE.md",
    "docs/BYOK_SECURITY_REVIEW.md",
]
SECRET_PATTERNS = [
    re.compile(r"sk-(?:proj-|ant-)?[A-Za-z0-9_\-]{24,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----"),
]


def run(cmd: list[str]) -> tuple[bool, str]:
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    output = (proc.stdout + proc.stderr).strip().splitlines()
    return proc.returncode == 0, (output[-1] if output else "")


def repo_files() -> list[Path]:
    ok, _ = run(["git", "rev-parse", "--is-inside-work-tree"])
    if ok:
        proc = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        return [ROOT / line for line in proc.stdout.splitlines() if line]
    return [
        p
        for p in ROOT.rglob("*")
        if p.is_file() and ".venv" not in p.parts and ".git" not in p.parts
    ]


def check_required_files() -> tuple[bool, str]:
    missing = [f for f in REQUIRED_FILES if not (ROOT / f).is_file()]
    return not missing, "all present" if not missing else "missing: " + ", ".join(missing)


def check_secrets(files: list[Path]) -> tuple[bool, str]:
    hits = []
    for path in files:
        if path.suffix.lower() in {".png", ".pdf", ".jpg"} or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(p.search(text) for p in SECRET_PATTERNS):
            hits.append(str(path.relative_to(ROOT)))
    return (
        not hits,
        "no key-like strings found" if not hits else "possible secrets in: " + ", ".join(hits),
    )


def check_hygiene(files: list[Path]) -> tuple[bool, str]:
    rel = [str(p.relative_to(ROOT)) for p in files]
    problems = [r for r in rel if r == ".env" or (r.startswith(".env.") and r != ".env.example")]
    problems += [
        r for r in rel if r.lower().endswith(".pdf") and not r.startswith("evaluation/fixtures/")
    ]
    problems += [r for r in rel if r.startswith((".venv/", ".claude/", ".playwright-mcp/"))]
    return (
        not problems,
        "only synthetic fixtures and no secrets files would be committed"
        if not problems
        else ("should not be committed: " + ", ".join(problems)),
    )


def main() -> int:
    files = repo_files()
    checks = [
        ("Required files", check_required_files()),
        (
            "Ruff lint",
            run([PY, "-m", "ruff", "check", "app.py", "src", "tests", "evaluation", "scripts"]),
        ),
        (
            "Ruff format",
            run(
                [
                    PY,
                    "-m",
                    "ruff",
                    "format",
                    "--check",
                    "app.py",
                    "src",
                    "tests",
                    "evaluation",
                    "scripts",
                ]
            ),
        ),
        ("Test suite (offline)", run([PY, "-m", "pytest", "-q"])),
        ("Secret scan", check_secrets(files)),
        ("Repository hygiene", check_hygiene(files)),
    ]
    width = max(len(name) for name, _ in checks)
    failed = 0
    for name, (ok, detail) in checks:
        failed += 0 if ok else 1
        print(f"{'PASS' if ok else 'FAIL'}  {name:<{width}}  {detail}")
    print(f"\n{len(checks) - failed}/{len(checks)} checks passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
