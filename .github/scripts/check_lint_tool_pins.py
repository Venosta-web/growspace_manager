"""Fail CI when lint tool pins or their local hooks drift."""

from __future__ import annotations

from pathlib import Path
import re
import sys

import yaml

ROOT = Path(__file__).resolve().parents[2]
HOOK_ENTRIES = {
    "ruff-check": "python3 .github/scripts/run_pinned_lint_tool.py ruff check --force-exclude",
    "ruff-format": "python3 .github/scripts/run_pinned_lint_tool.py ruff format --force-exclude",
    "yamllint": "python3 .github/scripts/run_pinned_lint_tool.py yamllint",
    "codespell": "python3 .github/scripts/run_pinned_lint_tool.py codespell",
}
LINT_TOOLS = ("ruff", "mypy", "yamllint", "codespell")


def check_lint_tool_pins(requirements: str, pre_commit_config: str) -> list[str]:
    """Return actionable errors for missing, duplicate, or mismatched pins."""
    errors: list[str] = []
    for tool in LINT_TOOLS:
        declarations = re.findall(
            rf"^{tool}(?:==([^\s#]+))?\s*(?:#.*)?$", requirements, re.MULTILINE
        )
        if len(declarations) != 1 or not declarations[0]:
            errors.append(f"{tool}: requirements.txt must have exactly one == pin")
    config = yaml.safe_load(pre_commit_config)
    repos = config.get("repos", []) if isinstance(config, dict) else []
    for hook_id, entry in HOOK_ENTRIES.items():
        matches = [
            (repo, hook)
            for repo in repos
            if isinstance(repo, dict)
            for hook in repo.get("hooks", [])
            if isinstance(hook, dict) and hook.get("id") == hook_id
        ]
        if (
            len(matches) != 1
            or matches[0][0].get("repo") != "local"
            or matches[0][1].get("entry") != entry
        ):
            errors.append(f"{hook_id}: expected one local hook with entry {entry!r}")
        elif matches[0][1].get("language") != "system":
            errors.append(f"{hook_id}: local hook must use language: system")
    return errors


def main() -> int:
    """Check the repository's pins and return a failing exit code on drift."""
    errors = check_lint_tool_pins(
        (ROOT / "requirements.txt").read_text(),
        (ROOT / ".pre-commit-config.yaml").read_text(),
    )
    for error in errors:
        sys.stderr.write(f"{error}\n")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
