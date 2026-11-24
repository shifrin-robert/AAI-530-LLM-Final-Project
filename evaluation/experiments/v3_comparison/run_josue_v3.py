"""Run PR #1's prompt v3 on the generalization set, under the name josue_v3.

This harness compares the two prompt v3 proposals. It is not part of the application.

It runs the unchanged evaluation runner (``evaluation/evaluation_runner.py``) with one
difference: the QA prompt ``josue_v3`` is loaded from ``prompts/josue_v3/grounded_qa_v3.md``
next to this file. That file is a byte-identical copy of ``prompts/grounded_qa_v3.md`` at commit
b0dc869 (PR #1).

Nothing in ``prompts/``, ``src/`` or the runner changes, so the app's prompt versions and its
default stay as they are. Both v3 files call themselves ``grounded_qa@v3``. Here the copy is
labelled ``grounded_qa@josue_v3``, so its runs can't be mistaken for runs of the default prompt.

Run it from the repository root:

    # Free: prints the runner's conservative cost estimate, then stops
    python -m evaluation.experiments.v3_comparison.run_josue_v3

    # Paid: only with an authorized budget
    python -m evaluation.experiments.v3_comparison.run_josue_v3 --allow-paid --max-cost-usd 0.10

A paid run writes the runner's usual files to ``results/`` next to this file. It also writes a
``.provenance.json`` file recording the hashes of the prompt, the code and the dataset.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import subprocess
from pathlib import Path

from docintel import prompting, qa
from docintel.config import PROJECT_ROOT
from evaluation import evaluation_runner

NAME = "josue_v3"
HERE = Path(__file__).resolve().parent
PROMPT_FILE = HERE / "prompts" / NAME / "grounded_qa_v3.md"
RESULTS = HERE / "results"
SOURCE = {
    "pull_request": 1,
    "branch": "josue/fix-windows-encoding",
    "commit": "b0dc869b017d4b7a4d2c5752c0b1bc720a27dae4",
    "path": "prompts/grounded_qa_v3.md",
}
FILE_SHA256 = "8073ae8325f6147c4e4764c77d9f299c5ae706742dfaf1e1556eaee40007d240"
INSTRUCTIONS_SHA256 = "725c73c047a11b6219222c2bada91f618a2cac12e506e34f9bb821bd86d47d06"
# Same dataset, repeats and runner defaults (model, retriever, settings) as the earlier
# generalization runs of v2 and v3 in evaluation/results/generalization/: only the prompt differs.
RUNNER_ARGS = ["--dataset", "generalization", "--provider", "openai", "--repeats", "3"]
TAG = "gen-josue-v3-x3"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def instructions_sha256(template: prompting.PromptTemplate) -> str:
    """The digest tests/test_prompting.py pins for v1, v2 and v3."""
    return hashlib.sha256((template.system + "\n" + template.user).encode("utf-8")).hexdigest()


def load_josue_v3() -> prompting.PromptTemplate:
    if sha256(PROMPT_FILE) != FILE_SHA256:
        raise SystemExit(f"{PROMPT_FILE} is not the copy of {SOURCE['commit'][:7]}; stopping.")
    template = prompting.load_prompt(PROMPT_FILE.stem, prompts_dir=PROMPT_FILE.parent)
    if instructions_sha256(template) != INSTRUCTIONS_SHA256:
        raise SystemExit("The josue_v3 instructions differ from the recorded hash; stopping.")
    # Only the label changes (the file says version v3). The text sent to the model does not.
    return dataclasses.replace(template, version=NAME)


def serve_prompt(template: prompting.PromptTemplate) -> dict[str, int]:
    """Serve josue_v3 to the QA pipeline in this process only. Other versions are unchanged."""
    served = {"case_runs": 0}
    original = qa.qa_prompt

    def qa_prompt(version: str) -> prompting.PromptTemplate:
        if version == NAME:
            served["case_runs"] += 1
            return template
        return original(version)

    qa.qa_prompt = qa_prompt
    # Lets the runner's --prompt-version accept the name. No prompt file has this name, so any code
    # path that bypassed qa.qa_prompt would fail rather than load prompts/grounded_qa_v3.md.
    prompting.QA_PROMPTS[NAME] = "josue_v3_is_served_only_by_the_experiment_harness"
    return served


def git(*args: str) -> str:
    out = subprocess.run(
        ["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True, check=True
    )
    return out.stdout.strip()


def provenance(run_file: Path, template: prompting.PromptTemplate, case_runs: int) -> dict:
    cases_path, fixtures_dir, _ = evaluation_runner.DATASETS["generalization"]
    outside = git("status", "--porcelain", "--untracked-files=all", "--", ".", ":(exclude).agents")
    return {
        "run_file": run_file.name,
        "run_sha256": sha256(run_file),
        "prompt": {
            "name": NAME,
            "label_used": template.label,
            "source": SOURCE,
            "copy": PROMPT_FILE.relative_to(PROJECT_ROOT).as_posix(),
            "file_sha256": FILE_SHA256,
            "instructions_sha256": INSTRUCTIONS_SHA256,
            "case_runs_served": case_runs,
        },
        "code": {
            "git_head": git("rev-parse", "HEAD"),
            "changes_outside_this_experiment": [
                line
                for line in outside.splitlines()
                if "evaluation/experiments/v3_comparison/" not in line
            ],
            "evaluation_runner_sha256": sha256(Path(evaluation_runner.__file__)),
            "harness_sha256": sha256(Path(__file__)),
        },
        "dataset": {
            "cases_sha256": sha256(cases_path),
            "fixtures_sha256": {p.name: sha256(p) for p in sorted(fixtures_dir.glob("*.pdf"))},
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run josue_v3 on the generalization set.")
    parser.add_argument("--allow-paid", action="store_true", help="required to call the API")
    parser.add_argument(
        "--max-cost-usd", type=float, default=0.10, help="abort if the estimate exceeds this"
    )
    args = parser.parse_args(argv)

    template = load_josue_v3()
    served = serve_prompt(template)
    before = set(RESULTS.glob("*.json"))
    runner_args = [
        *RUNNER_ARGS,
        *("--prompt-version", NAME, "--max-cost-usd", str(args.max_cost_usd)),
        *("--out", str(RESULTS), "--tag", TAG),
    ]
    if args.allow_paid:
        runner_args.append("--allow-paid")
    code = evaluation_runner.main(runner_args)
    new_runs = sorted(
        p for p in set(RESULTS.glob("*.json")) - before if not p.name.endswith(".provenance.json")
    )
    if code != 0 or not new_runs:
        return code
    run_file = new_runs[-1]
    record = provenance(run_file, template, served["case_runs"])
    sidecar = run_file.with_name(f"{run_file.stem}.provenance.json")
    sidecar.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"josue_v3 was served to {served['case_runs']} case runs. Wrote {sidecar}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
