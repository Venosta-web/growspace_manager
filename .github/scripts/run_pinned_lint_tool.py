"""Run a lint tool from the shared repository venv or the CI environment."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

TOOLS = {"ruff", "yamllint", "codespell"}


def tool_path(tool: str) -> str | None:
    """Prefer the checkout's shared venv, then CI's installed tool."""
    common_dir = subprocess.check_output(
        ["git", "rev-parse", "--git-common-dir"], text=True
    ).strip()
    candidate = Path(common_dir).resolve().parent / ".venv" / "bin" / tool
    if candidate.is_file():
        return str(candidate)
    return shutil.which(tool)


def main(args: list[str]) -> int:
    """Replace this process with the selected lint tool."""
    if not args or args[0] not in TOOLS:
        sys.stderr.write("expected ruff, yamllint, or codespell\n")
        return 2
    binary = tool_path(args[0])
    if binary is None:
        sys.stderr.write(f"{args[0]} is not installed\n")
        return 2
    os.execv(binary, [binary, *args[1:]])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
