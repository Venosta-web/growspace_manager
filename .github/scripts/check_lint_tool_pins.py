"""Fail CI when pre-commit lint hooks drift from requirements.txt."""

from __future__ import annotations

from pathlib import Path
import re
import sys

import yaml

ROOT = Path(__file__).resolve().parents[2]
HOOK_REPOS = {
    "ruff": "https://github.com/astral-sh/ruff-pre-commit",
    "yamllint": "https://github.com/adrienverge/yamllint.git",
}
LINT_TOOLS = ("ruff", "mypy", "yamllint")


def check_lint_tool_pins(requirements: str, pre_commit_config: str) -> list[str]:
    """Return actionable errors for missing, duplicate, or mismatched pins."""
    errors: list[str] = []
    pins: dict[str, str] = {}
    for tool in LINT_TOOLS:
        declarations = re.findall(
            rf"^{tool}(?:==([^\s#]+))?\s*(?:#.*)?$", requirements, re.MULTILINE
        )
        if len(declarations) != 1 or not declarations[0]:
            errors.append(f"{tool}: requirements.txt must have exactly one == pin")
        else:
            pins[tool] = declarations[0]

    config = yaml.safe_load(pre_commit_config)
    repos = config.get("repos", []) if isinstance(config, dict) else []
    for tool, url in HOOK_REPOS.items():
        matches = [
            repo for repo in repos if isinstance(repo, dict) and repo.get("repo") == url
        ]
        if len(matches) != 1:
            errors.append(
                f"{tool}: .pre-commit-config.yaml must contain exactly one {url} hook repo"
            )
            continue
        revision = matches[0].get("rev")
        if tool in pins and revision != f"v{pins[tool]}":
            errors.append(
                f"{tool}: requirements.txt pins {pins[tool]}, "
                f"but .pre-commit-config.yaml rev is {revision!r}"
            )
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
