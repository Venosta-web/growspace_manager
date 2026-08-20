"""Regression tests for the active prerelease publishing channel."""

from pathlib import Path
import runpy

from awesomeversion import AwesomeVersion
import yaml

REPO_ROOT = Path(__file__).parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github/workflows/prerelease.yaml"
STABLE_WORKFLOW_PATH = REPO_ROOT / ".github/workflows/release.yaml"
VERSION_SCRIPT = REPO_ROOT / ".github/scripts/prerelease_version.py"


def _workflow_steps() -> list[dict]:
    workflow = _workflow()
    return workflow["jobs"]["build"]["steps"]


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW_PATH.read_text())


def _step(name: str) -> dict:
    return next(step for step in _workflow_steps() if step.get("name") == name)


def test_prerelease_publishing_contract() -> None:
    """The active release must be monotonic, correctly tagged, and cleaned up."""
    version_module = runpy.run_path(VERSION_SCRIPT)

    prerelease = version_module["prerelease_version"]("1.2.1", 123)
    assert prerelease == "1.2.2b123"
    assert AwesomeVersion(prerelease) > AwesomeVersion("1.2.1")
    assert AwesomeVersion(prerelease) > AwesomeVersion("1.0.0")

    assert _workflow()["concurrency"] == {
        "group": "prerelease-publish",
        "cancel-in-progress": False,
    }

    release = _step("Create Pre-release")
    assert release["with"]["target_commitish"] == "${{ github.sha }}"
    assert release["with"]["fail_on_unmatched_files"] is True

    verification = _step("Verify release tag")
    assert "GITHUB_SHA" in verification["run"]
    assert "git/ref/tags" in verification["run"]

    cleanup = _step("Delete Older Pre-releases")

    assert cleanup["with"]["delete_prerelease_only"] is True
    assert "delete_tag_pattern" not in cleanup["with"]


def test_stable_publishing_contract() -> None:
    """A main push must publish and verify the next stable patch release."""
    version_module = runpy.run_path(VERSION_SCRIPT)
    assert version_module["next_stable_version"]("1.2.1") == "1.2.2"

    workflow = yaml.safe_load(STABLE_WORKFLOW_PATH.read_text())
    assert workflow["on"] == {
        "push": {"branches": ["main"]},
        "workflow_dispatch": None,
    }
    assert workflow["concurrency"] == {
        "group": "stable-publish",
        "cancel-in-progress": False,
    }

    steps = workflow["jobs"]["build"]["steps"]
    release = next(step for step in steps if step.get("name") == "Create Release")
    assert release["with"]["tag_name"] == "v${{ steps.version_step.outputs.version }}"
    assert (
        release["with"]["target_commitish"] == "${{ steps.stable_commit.outputs.sha }}"
    )
    assert release["with"]["fail_on_unmatched_files"] is True

    verification = next(
        step for step in steps if step.get("name") == "Verify release tag"
    )
    assert "TARGET_SHA" in verification["run"]
    assert "git/ref/tags" in verification["run"]
