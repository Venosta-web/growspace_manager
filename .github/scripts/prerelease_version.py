"""Generate the next monotonic prerelease version for the active GSM channel."""

import argparse
import re
import sys

STABLE_VERSION = re.compile(r"^(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)$")


def prerelease_version(stable_version: str, run_number: int) -> str:
    """Return a beta of the patch following stable_version."""
    match = STABLE_VERSION.fullmatch(stable_version)
    if match is None:
        raise ValueError(f"Expected a stable X.Y.Z version, got {stable_version!r}")
    if run_number < 1:
        raise ValueError("GitHub workflow run number must be positive")

    major = int(match["major"])
    minor = int(match["minor"])
    patch = int(match["patch"]) + 1
    return f"{major}.{minor}.{patch}b{run_number}"


def main() -> None:
    """Print the prerelease version for the workflow."""
    parser = argparse.ArgumentParser()
    parser.add_argument("stable_version")
    parser.add_argument("run_number", type=int)
    args = parser.parse_args()
    sys.stdout.write(f"{prerelease_version(args.stable_version, args.run_number)}\n")


if __name__ == "__main__":
    main()
