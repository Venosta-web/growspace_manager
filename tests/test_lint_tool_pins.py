"""The CI lint pin check rejects drift before pre-commit runs."""

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

REQUIREMENTS = "ruff==0.15.12\nmypy==1.20.2\nyamllint==1.37.1\n"
HOOKS = """repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.15.12
  - repo: https://github.com/adrienverge/yamllint.git
    rev: v1.37.1
"""


def test_checked_in_lint_pins_agree() -> None:
    assert (
        checker.check_lint_tool_pins(
            (ROOT / "requirements.txt").read_text(),
            (ROOT / ".pre-commit-config.yaml").read_text(),
        )
        == []
    )


@pytest.mark.parametrize(
    ("requirements", "hooks", "expected"),
    [
        (
            REQUIREMENTS.replace("ruff==0.15.12", "ruff==0.15.13"),
            HOOKS,
            "ruff: requirements.txt pins 0.15.13, but .pre-commit-config.yaml rev is 'v0.15.12'",
        ),
        (
            REQUIREMENTS,
            HOOKS.replace("v1.37.1", "v1.37.0"),
            "yamllint: requirements.txt pins 1.37.1, but .pre-commit-config.yaml rev is 'v1.37.0'",
        ),
        (
            REQUIREMENTS.replace("mypy==1.20.2", "mypy"),
            HOOKS,
            "mypy: requirements.txt must have exactly one == pin",
        ),
        (
            REQUIREMENTS + "ruff==0.15.12\n",
            HOOKS,
            "ruff: requirements.txt must have exactly one == pin",
        ),
        (
            REQUIREMENTS,
            HOOKS.replace("https://github.com/astral-sh/ruff-pre-commit", "local"),
            "ruff: .pre-commit-config.yaml must contain exactly one https://github.com/astral-sh/ruff-pre-commit hook repo",
        ),
    ],
)
def test_lint_pin_check_reports_drift(
    requirements: str, hooks: str, expected: str
) -> None:
    assert expected in checker.check_lint_tool_pins(requirements, hooks)


def test_cli_exits_successfully_for_checked_in_pins() -> None:
    with pytest.raises(SystemExit, match="^0$"):
        runpy.run_path(
            str(ROOT / ".github/scripts/check_lint_tool_pins.py"), run_name="__main__"
        )


def test_cli_reports_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "requirements.txt").write_text(
        REQUIREMENTS.replace("ruff==0.15.12", "ruff==0.15.13")
    )
    (tmp_path / ".pre-commit-config.yaml").write_text(HOOKS)
    monkeypatch.setattr(checker, "ROOT", tmp_path)

    assert checker.main() == 1
    assert (
        "ruff: requirements.txt pins 0.15.13, but .pre-commit-config.yaml rev is 'v0.15.12'"
        in capsys.readouterr().err
    )
