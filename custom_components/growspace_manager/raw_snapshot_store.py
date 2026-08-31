"""Private storage for original camera bytes captured by vision checkups."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from pathlib import Path

_LOGGER = logging.getLogger(__name__)

RAW_SNAPSHOT_RETENTION = timedelta(days=90)

_CONTENT_TYPE_SUFFIXES = {
    "image/gif": ".gif",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def _suffix_for_content_type(content_type: object) -> str:
    """Return a truthful suffix for camera bytes without decoding them."""
    if not isinstance(content_type, str):
        return ".bin"
    media_type = content_type.partition(";")[0].strip().lower()
    return _CONTENT_TYPE_SUFFIXES.get(media_type, ".bin")


class RawSnapshotStore:
    """Persist original camera responses and bound their time on disk."""

    def __init__(
        self,
        root: Path,
        retention: timedelta = RAW_SNAPSHOT_RETENTION,
    ) -> None:
        """Initialize the store below a private media-source directory."""
        self._root = root
        self._retention = retention

    def save(
        self,
        growspace_id: str,
        capture_stem: str,
        content: bytes,
        content_type: object,
        captured_at: datetime,
    ) -> Path:
        """Prune expired captures, then write the camera bytes unchanged."""
        growspace_dir = self._root / growspace_id
        growspace_dir.mkdir(parents=True, exist_ok=True)
        self._prune(captured_at)

        suffix = _suffix_for_content_type(content_type)
        destination = growspace_dir / f"{capture_stem}_raw{suffix}"
        temporary = destination.with_suffix(f"{destination.suffix}.tmp")
        try:
            temporary.write_bytes(content)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)

        return destination

    def _prune(self, captured_at: datetime) -> None:
        """Remove only expired raw artifacts; public snapshots are out of scope."""
        cutoff = captured_at.timestamp() - self._retention.total_seconds()
        try:
            candidates = self._root.rglob("*_raw.*")
            for candidate in candidates:
                try:
                    if candidate.stat().st_mtime < cutoff:
                        candidate.unlink(missing_ok=True)
                except OSError:
                    _LOGGER.warning(
                        "Failed to inspect or prune raw vision snapshot %s",
                        candidate,
                        exc_info=True,
                    )
        except OSError:
            _LOGGER.warning(
                "Failed to scan raw vision snapshot store %s for retention",
                self._root,
                exc_info=True,
            )
