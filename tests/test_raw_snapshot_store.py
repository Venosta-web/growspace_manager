"""Tests for byte-faithful raw vision snapshot storage."""

from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
from unittest.mock import MagicMock

from custom_components.growspace_manager.raw_snapshot_store import RawSnapshotStore


def test_save_preserves_original_bytes_and_content_type_suffix(tmp_path: Path) -> None:
    """The raw artifact is not decoded or re-encoded before persistence."""
    original = b"RIFF\x00\x01WEBP-camera-response"
    store = RawSnapshotStore(tmp_path)

    saved = store.save(
        "tent1",
        "20260831_120000_123456_camera_canopy",
        original,
        "image/webp; charset=binary",
        datetime(2026, 8, 31, 12, tzinfo=UTC),
    )

    assert saved == (
        tmp_path / "tent1" / "20260831_120000_123456_camera_canopy_raw.webp"
    )
    assert saved.read_bytes() == original


def test_save_uses_bin_for_an_unknown_camera_content_type(tmp_path: Path) -> None:
    """Unknown formats remain byte-faithful without claiming to be JPEGs."""
    saved = RawSnapshotStore(tmp_path).save(
        "tent1",
        "capture",
        b"opaque-camera-bytes",
        "application/octet-stream",
        datetime(2026, 8, 31, 12, tzinfo=UTC),
    )

    assert saved.name == "capture_raw.bin"
    assert saved.read_bytes() == b"opaque-camera-bytes"


def test_save_prunes_only_expired_raw_artifacts(tmp_path: Path) -> None:
    """Retention cannot remove public or processed snapshots by broad glob."""
    captured_at = datetime(2026, 8, 31, 12, tzinfo=UTC)
    growspace_dir = tmp_path / "tent1"
    growspace_dir.mkdir()

    expired_raw = growspace_dir / "expired_raw.jpg"
    recent_raw = growspace_dir / "recent_raw.jpg"
    unrelated_processed = growspace_dir / "expired_processed.jpg"
    for path in (expired_raw, recent_raw, unrelated_processed):
        path.write_bytes(b"existing")

    expired_mtime = (captured_at - timedelta(days=91)).timestamp()
    recent_mtime = (captured_at - timedelta(days=89)).timestamp()
    os.utime(expired_raw, (expired_mtime, expired_mtime))
    os.utime(unrelated_processed, (expired_mtime, expired_mtime))
    os.utime(recent_raw, (recent_mtime, recent_mtime))

    RawSnapshotStore(tmp_path).save(
        "tent1",
        "current",
        b"current",
        "image/jpeg",
        captured_at,
    )

    assert not expired_raw.exists()
    assert recent_raw.exists()
    assert unrelated_processed.exists()


def test_prune_continues_when_one_raw_artifact_cannot_be_inspected(caplog) -> None:
    """One inaccessible artifact does not disable retention for future captures."""
    candidate = MagicMock(spec=Path)
    candidate.stat.side_effect = OSError("unreadable")
    root = MagicMock(spec=Path)
    root.rglob.return_value = [candidate]

    RawSnapshotStore(root)._prune(datetime(2026, 8, 31, 12, tzinfo=UTC))

    assert "Failed to inspect or prune raw vision snapshot" in caplog.text


def test_prune_tolerates_an_unreadable_raw_store(caplog) -> None:
    """A retention scan failure is logged without breaking capture processing."""
    root = MagicMock(spec=Path)
    root.rglob.side_effect = OSError("unreadable store")

    RawSnapshotStore(root)._prune(datetime(2026, 8, 31, 12, tzinfo=UTC))

    assert "Failed to scan raw vision snapshot store" in caplog.text
