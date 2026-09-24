"""Local lint hooks execute the installed tool without another version pin."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import runpy
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "run_pinned_lint_tool", ROOT / ".github/scripts/run_pinned_lint_tool.py"
)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def test_shared_venv_is_preferred(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    common_dir = tmp_path / ".git"
    common_dir.mkdir()
    binary = tmp_path / ".venv/bin/ruff"
    binary.parent.mkdir(parents=True)
    binary.touch()
    monkeypatch.setattr(
        runner.subprocess, "check_output", lambda *_args, **_kwargs: str(common_dir)
    )
    monkeypatch.setattr(runner.shutil, "which", lambda _tool: "/usr/bin/ruff")

    assert runner.tool_path("ruff") == str(binary)


def test_ci_path_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    common_dir = tmp_path / ".git"
    common_dir.mkdir()
    monkeypatch.setattr(
        runner.subprocess, "check_output", lambda *_args, **_kwargs: str(common_dir)
    )
    monkeypatch.setattr(runner.shutil, "which", lambda _tool: "/usr/bin/yamllint")

    assert runner.tool_path("yamllint") == "/usr/bin/yamllint"


def test_main_rejects_unknown_or_missing_tool(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert runner.main([]) == 2
    assert runner.main(["pytest"]) == 2
    assert "expected ruff, yamllint, or codespell" in capsys.readouterr().err


def test_main_rejects_uninstalled_tool(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(runner, "tool_path", lambda _tool: None)
    assert runner.main(["yamllint"]) == 2
    assert "yamllint is not installed" in capsys.readouterr().err


def test_main_executes_tool_with_hook_args(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "tool_path", lambda _tool: "/venv/bin/ruff")
    calls: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(
        runner.os, "execv", lambda binary, args: calls.append((binary, args))
    )

    assert runner.main(["ruff", "check", "--fix", "example.py"]) == 0
    assert calls == [
        ("/venv/bin/ruff", ["/venv/bin/ruff", "check", "--fix", "example.py"])
    ]


def test_cli_rejects_missing_tool_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["run_pinned_lint_tool.py"])
    with pytest.raises(SystemExit, match="^2$"):
        runpy.run_path(
            str(ROOT / ".github/scripts/run_pinned_lint_tool.py"),
            run_name="__main__",
        )
