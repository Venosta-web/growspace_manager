"""Run a Python hook tool from the worktree's venv, the main venv, or CI's PATH.

Every Python pre-commit hook goes through here so that a worktree with its own
``.venv`` is checked with that environment rather than the main checkout's.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

LINT_TOOLS = {"ruff", "yamllint", "codespell"}
VENV_ONLY_TOOLS = {"pytest", "mypy"}
TOOLS = LINT_TOOLS | VENV_ONLY_TOOLS


def _git(*args: str) -> Path:
    """Return a git rev-parse path, resolved against the current directory."""
    output = subprocess.check_output(["git", "rev-parse", *args], text=True)
    return Path(output.strip()).resolve()


def venv_candidates(tool: str) -> list[Path]:
    """Return the worktree's then the main checkout's venv binary for a tool."""
    worktree_venv = _git("--show-toplevel") / ".venv"
    main_venv = _git("--git-common-dir").parent / ".venv"
    candidates = [worktree_venv / "bin" / tool]
    if main_venv != worktree_venv:
        candidates.append(main_venv / "bin" / tool)
    return candidates


def tool_path(tool: str, candidates: list[Path]) -> str | None:
    """Pick the first venv binary; only lint tools may fall back to PATH."""
    for candidate in candidates:
        # A worktree's .venv may be a real directory or a link to the main
        # venv; is_file() follows the link either way.
        if candidate.is_file():
            return str(candidate)
    if tool in LINT_TOOLS:
        return shutil.which(tool)
    return None


def main(args: list[str]) -> int:
    """Replace this process with the selected tool."""
    if not args or args[0] not in TOOLS:
        sys.stderr.write(f"expected one of {', '.join(sorted(TOOLS))}\n")
        return 2
    tool = args[0]
    candidates = venv_candidates(tool)
    binary = tool_path(tool, candidates)
    if binary is None:
        tried = [str(candidate) for candidate in candidates]
        if tool in LINT_TOOLS:
            tried.append("PATH")
        sys.stderr.write(f"{tool} is not installed; tried {', '.join(tried)}\n")
        return 2
    os.execv(binary, [binary, *args[1:]])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
