"""Generate the next monotonic prerelease version for the active GSM channel."""

import argparse
import re
import sys

STABLE_VERSION = re.compile(r"^(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)$")


def next_stable_version(stable_version: str) -> str:
    """Return the patch release following stable_version."""
    match = STABLE_VERSION.fullmatch(stable_version)
    if match is None:
        raise ValueError(f"Expected a stable X.Y.Z version, got {stable_version!r}")

    major = int(match["major"])
    minor = int(match["minor"])
    patch = int(match["patch"]) + 1
    return f"{major}.{minor}.{patch}"


def prerelease_version(stable_version: str, run_number: int) -> str:
    """Return a beta of the patch following stable_version."""
    if run_number < 1:
        raise ValueError("GitHub workflow run number must be positive")

    return f"{next_stable_version(stable_version)}b{run_number}"


def main() -> None:
    """Print the requested release version for a publishing workflow."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--stable", action="store_true")
    parser.add_argument("stable_version")
    parser.add_argument("run_number", nargs="?", type=int)
    args = parser.parse_args()
    if args.stable:
        if args.run_number is not None:
            parser.error("run_number is not accepted with --stable")
        version = next_stable_version(args.stable_version)
    else:
        if args.run_number is None:
            parser.error("run_number is required unless --stable is used")
        version = prerelease_version(args.stable_version, args.run_number)
    sys.stdout.write(f"{version}\n")


if __name__ == "__main__":
    main()
