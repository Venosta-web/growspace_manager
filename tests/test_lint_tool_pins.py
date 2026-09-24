"""Lint hooks use the versions pinned in requirements.txt."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import runpy

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "check_lint_tool_pins", ROOT / ".github/scripts/check_lint_tool_pins.py"
)
assert SPEC is not None and SPEC.loader is not None
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)

REQUIREMENTS = "ruff==0.15.12\nmypy==1.20.2\nyamllint==1.37.1\ncodespell==2.4.3\n"
HOOKS = """repos:
  - repo: local
    hooks:
      - id: ruff-check
        entry: python3 .github/scripts/run_pinned_lint_tool.py ruff check --force-exclude
        language: system
      - id: ruff-format
        entry: python3 .github/scripts/run_pinned_lint_tool.py ruff format --force-exclude
        language: system
      - id: yamllint
        entry: python3 .github/scripts/run_pinned_lint_tool.py yamllint
        language: system
      - id: codespell
        entry: python3 .github/scripts/run_pinned_lint_tool.py codespell
        language: system
"""


def test_checked_in_lint_pins_agree() -> None:
    assert (
        checker.check_lint_tool_pins(
            (ROOT / "requirements.txt").read_text(),
            (ROOT / ".pre-commit-config.yaml").read_text(),
        )
        == []
    )


def test_tool_pin_changes_without_hook_edit() -> None:
    assert (
        checker.check_lint_tool_pins(
            REQUIREMENTS.replace("ruff==0.15.12", "ruff==0.15.13"), HOOKS
        )
        == []
    )


@pytest.mark.parametrize("tool", ["ruff", "mypy", "yamllint", "codespell"])
def test_unpinned_tool_is_rejected(tool: str) -> None:
    requirements = REQUIREMENTS.replace(f"{tool}==", f"{tool}#")
    assert f"{tool}: requirements.txt must have exactly one == pin" in (
        checker.check_lint_tool_pins(requirements, HOOKS)
    )


@pytest.mark.parametrize("hook", ["ruff-check", "ruff-format", "yamllint", "codespell"])
def test_missing_or_changed_hook_is_rejected(hook: str) -> None:
    changed = HOOKS.replace(f"id: {hook}", f"id: missing-{hook}")
    assert f"{hook}: expected one local hook" in "\n".join(
        checker.check_lint_tool_pins(REQUIREMENTS, changed)
    )


def test_non_system_hook_is_rejected() -> None:
    changed = HOOKS.replace("language: system", "language: python", 1)
    assert "ruff-check: local hook must use language: system" in (
        checker.check_lint_tool_pins(REQUIREMENTS, changed)
    )


def test_cli_exits_successfully_for_checked_in_pins() -> None:
    with pytest.raises(SystemExit, match="^0$"):
        runpy.run_path(
            str(ROOT / ".github/scripts/check_lint_tool_pins.py"), run_name="__main__"
        )


def test_cli_reports_invalid_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "requirements.txt").write_text(REQUIREMENTS.replace("mypy==", "mypy#"))
    (tmp_path / ".pre-commit-config.yaml").write_text(HOOKS)
    monkeypatch.setattr(checker, "ROOT", tmp_path)

    assert checker.main() == 1
    assert "mypy: requirements.txt must have exactly one == pin" in (
        capsys.readouterr().err
    )
