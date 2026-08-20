"""Serialization cache manager for growspace data.

This module provides a dedicated cache manager to store serialized growspace data,
improving performance by avoiding repeated expensive serialization operations.
"""

from __future__ import annotations

from typing import Any


class CacheManager:
    """Manages serialization cache for growspace data.

    The CacheManager provides a simple key-value cache for storing serialized
    growspace data alongside the timestamp it was cached at, so callers can
    apply their own TTL. It supports per-growspace invalidation and full
    cache clearing.

    Example:
        >>> cache = CacheManager()
        >>> cache.set("growspace_1", (0.0, {"name": "Main", "plants": []}))
        >>> data = cache.get("growspace_1")
        >>> cache.invalidate("growspace_1")
        >>> cache.get("growspace_1")  # Returns None
    """

    def __init__(self) -> None:
        """Initialize an empty cache."""
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}

    def get(self, growspace_id: str) -> tuple[float, dict[str, Any]] | None:
        """Get the cached (timestamp, data) entry for a growspace.

        Args:
            growspace_id: The unique identifier for the growspace.

        Returns:
            The cached (timestamp, data) entry if present, None otherwise.
        """
        return self._cache.get(growspace_id)

    def set(self, growspace_id: str, data: tuple[float, dict[str, Any]]) -> None:
        """Store a (timestamp, data) entry in cache.

        Args:
            growspace_id: The unique identifier for the growspace.
            data: The (timestamp, serialized data) entry to cache.
        """
        self._cache[growspace_id] = data

    def invalidate(self, growspace_id: str | None = None) -> None:
        """Invalidate cache entries.

        Args:
            growspace_id: Specific growspace ID to invalidate, or None to clear all.
                         If None, the entire cache is cleared.
        """
        if growspace_id is None:
            self._cache.clear()
        else:
            self._cache.pop(growspace_id, None)

    def clear(self) -> None:
        """Clear all cache entries.

        This is equivalent to calling `invalidate(None)`.
        """
        self._cache.clear()

    def __contains__(self, growspace_id: str) -> bool:
        """Check if a growspace is cached.

        Args:
            growspace_id: The growspace identifier to check.

        Returns:
            True if the growspace data is cached, False otherwise.

        Example:
            >>> cache = CacheManager()
            >>> cache.set("gs1", (0.0, {}))
            >>> "gs1" in cache
            True
            >>> "gs2" in cache
            False
        """
        return growspace_id in self._cache

    def __len__(self) -> int:
        """Get the number of cached entries.

        Returns:
            The number of growspaces currently cached.

        Example:
            >>> cache = CacheManager()
            >>> len(cache)
            0
            >>> cache.set("gs1", (0.0, {}))
            >>> len(cache)
            1
        """
        return len(self._cache)

    def __repr__(self) -> str:
        """Return a string representation of the cache manager.

        Returns:
            A string showing the number of cached entries.
        """
        return f"CacheManager(entries={len(self._cache)})"
