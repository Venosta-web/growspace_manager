"""Python hooks run the worktree's own venv, then the main venv, then PATH."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import runpy
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "run_venv_tool", ROOT / ".github/scripts/run_venv_tool.py"
)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)

ALL_TOOLS = ["pytest", "mypy", "ruff", "yamllint", "codespell"]


def _install(venv: Path, *tools: str) -> None:
    (venv / "bin").mkdir(parents=True, exist_ok=True)
    for tool in tools:
        (venv / "bin" / tool).touch()


@pytest.fixture
def checkouts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """A real main checkout with a worktree at the hooks' .worktrees/<name> depth."""
    # A hook's environment would otherwise point git at the repository under test.
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
        monkeypatch.delenv(name, raising=False)
    main = (tmp_path / "growspace_manager").resolve()
    worktree = main / ".worktrees" / "feature"
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com"]
    subprocess.run([*git, "init", "-q", str(main)], check=True)
    subprocess.run(
        [*git, "-C", str(main), "commit", "-q", "--allow-empty", "-m", "init"],
        check=True,
    )
    subprocess.run(
        [*git, "-C", str(main), "worktree", "add", "-q", "-b", "f", str(worktree)],
        check=True,
    )
    monkeypatch.chdir(worktree)
    monkeypatch.setattr(runner.shutil, "which", lambda tool: f"/usr/bin/{tool}")
    return main, worktree


@pytest.mark.parametrize("tool", ALL_TOOLS)
def test_private_worktree_venv_wins(checkouts: tuple[Path, Path], tool: str) -> None:
    main, worktree = checkouts
    _install(main / ".venv", tool)
    _install(worktree / ".venv", tool)

    candidates = runner.venv_candidates(tool)

    assert runner.tool_path(tool, candidates) == str(worktree / ".venv/bin" / tool)


@pytest.mark.parametrize("tool", ALL_TOOLS)
def test_linked_worktree_venv_runs_the_main_venv(
    checkouts: tuple[Path, Path], tool: str
) -> None:
    main, worktree = checkouts
    _install(main / ".venv", tool)
    (worktree / ".venv").symlink_to(main / ".venv")

    binary = runner.tool_path(tool, runner.venv_candidates(tool))

    assert binary == str(worktree / ".venv/bin" / tool)
    assert Path(binary).resolve() == main / ".venv/bin" / tool


@pytest.mark.parametrize("tool", ALL_TOOLS)
def test_worktree_without_venv_falls_back_to_main_venv(
    checkouts: tuple[Path, Path], tool: str
) -> None:
    main, _worktree = checkouts
    _install(main / ".venv", tool)

    assert runner.tool_path(tool, runner.venv_candidates(tool)) == str(
        main / ".venv/bin" / tool
    )


def test_main_checkout_resolves_its_own_venv_once(
    checkouts: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    main, _worktree = checkouts
    monkeypatch.chdir(main)

    assert runner.venv_candidates("pytest") == [main / ".venv/bin/pytest"]


@pytest.mark.parametrize("tool", ["ruff", "yamllint", "codespell"])
def test_lint_tools_fall_back_to_path(checkouts: tuple[Path, Path], tool: str) -> None:
    assert runner.tool_path(tool, runner.venv_candidates(tool)) == f"/usr/bin/{tool}"


@pytest.mark.parametrize("tool", ["pytest", "mypy"])
def test_venv_only_tools_fail_naming_both_venvs(
    checkouts: tuple[Path, Path], tool: str, capsys: pytest.CaptureFixture[str]
) -> None:
    main, worktree = checkouts

    assert runner.main([tool]) == 2
    assert capsys.readouterr().err == (
        f"{tool} is not installed; tried {worktree}/.venv/bin/{tool}, "
        f"{main}/.venv/bin/{tool}\n"
    )


def test_lint_tool_missing_everywhere_names_path_too(
    checkouts: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    main, worktree = checkouts
    monkeypatch.setattr(runner.shutil, "which", lambda _tool: None)

    assert runner.main(["yamllint"]) == 2
    assert capsys.readouterr().err == (
        f"yamllint is not installed; tried {worktree}/.venv/bin/yamllint, "
        f"{main}/.venv/bin/yamllint, PATH\n"
    )


def test_main_rejects_unknown_or_missing_tool(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert runner.main([]) == 2
    assert runner.main(["black"]) == 2
    assert "expected one of codespell, mypy, pytest, ruff, yamllint" in (
        capsys.readouterr().err
    )


def test_main_executes_tool_with_hook_args(
    checkouts: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _main, worktree = checkouts
    _install(worktree / ".venv", "mypy")
    calls: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(
        runner.os, "execv", lambda binary, args: calls.append((binary, args))
    )

    assert runner.main(["mypy", "--follow-imports=silent", "example.py"]) == 0
    binary = str(worktree / ".venv/bin/mypy")
    assert calls == [(binary, [binary, "--follow-imports=silent", "example.py"])]


def test_cli_rejects_missing_tool_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["run_venv_tool.py"])
    with pytest.raises(SystemExit, match="^2$"):
        runpy.run_path(
            str(ROOT / ".github/scripts/run_venv_tool.py"), run_name="__main__"
        )
