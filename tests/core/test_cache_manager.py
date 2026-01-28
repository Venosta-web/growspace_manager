"""Tests for CacheManager class.

This module contains comprehensive unit tests for the CacheManager,
ensuring correct cache behavior including get/set operations,
invalidation strategies, and protocol implementations.
"""

from __future__ import annotations

from custom_components.growspace_manager.cache import CacheManager


class TestCacheManagerBasics:
    """Test basic cache operations."""

    def test_cache_init_empty(self):
        """Test that cache initializes empty."""
        cache = CacheManager()
        assert len(cache) == 0

    def test_cache_get_miss(self):
        """Test cache miss returns None."""
        cache = CacheManager()
        assert cache.get("nonexistent") is None

    def test_cache_set_and_get(self):
        """Test setting and retrieving cached data."""
        cache = CacheManager()
        data = {"name": "Test Growspace", "plants": []}

        cache.set("gs1", data)
        retrieved = cache.get("gs1")

        assert retrieved == data
        assert retrieved is data  # Same object reference

    def test_cache_set_overwrites(self):
        """Test that setting same key overwrites previous value."""
        cache = CacheManager()

        cache.set("gs1", {"version": 1})
        cache.set("gs1", {"version": 2})

        assert cache.get("gs1") == {"version": 2}

    def test_cache_multiple_entries(self):
        """Test caching multiple growspaces."""
        cache = CacheManager()

        cache.set("gs1", {"id": "gs1"})
        cache.set("gs2", {"id": "gs2"})
        cache.set("gs3", {"id": "gs3"})

        assert len(cache) == 3
        assert cache.get("gs1") == {"id": "gs1"}
        assert cache.get("gs2") == {"id": "gs2"}
        assert cache.get("gs3") == {"id": "gs3"}


class TestCacheInvalidation:
    """Test cache invalidation strategies."""

    def test_invalidate_specific_entry(self):
        """Test invalidating a specific cache entry."""
        cache = CacheManager()
        cache.set("gs1", {"a": 1})
        cache.set("gs2", {"b": 2})

        cache.invalidate("gs1")

        assert cache.get("gs1") is None
        assert cache.get("gs2") == {"b": 2}
        assert len(cache) == 1

    def test_invalidate_nonexistent_entry(self):
        """Test invalidating a non-existent entry doesn't raise error."""
        cache = CacheManager()
        cache.set("gs1", {"a": 1})

        # Should not raise
        cache.invalidate("nonexistent")

        assert cache.get("gs1") == {"a": 1}
        assert len(cache) == 1

    def test_invalidate_all_with_none(self):
        """Test invalidating all entries with None parameter."""
        cache = CacheManager()
        cache.set("gs1", {"a": 1})
        cache.set("gs2", {"b": 2})
        cache.set("gs3", {"c": 3})

        cache.invalidate(None)

        assert len(cache) == 0
        assert cache.get("gs1") is None
        assert cache.get("gs2") is None
        assert cache.get("gs3") is None

    def test_clear_all_entries(self):
        """Test clearing all cache entries."""
        cache = CacheManager()
        cache.set("gs1", {"a": 1})
        cache.set("gs2", {"b": 2})

        cache.clear()

        assert len(cache) == 0
        assert cache.get("gs1") is None


class TestCacheProtocols:
    """Test Python protocol implementations."""

    def test_contains_with_cached_entry(self):
        """Test __contains__ returns True for cached entries."""
        cache = CacheManager()
        cache.set("gs1", {"a": 1})

        assert "gs1" in cache

    def test_contains_with_missing_entry(self):
        """Test __contains__ returns False for missing entries."""
        cache = CacheManager()

        assert "nonexistent" not in cache

    def test_contains_after_invalidation(self):
        """Test __contains__ returns False after invalidation."""
        cache = CacheManager()
        cache.set("gs1", {"a": 1})

        assert "gs1" in cache

        cache.invalidate("gs1")

        assert "gs1" not in cache

    def test_len_empty_cache(self):
        """Test len() on empty cache."""
        cache = CacheManager()
        assert len(cache) == 0

    def test_len_with_entries(self):
        """Test len() reflects number of cached entries."""
        cache = CacheManager()

        assert len(cache) == 0

        cache.set("gs1", {})
        assert len(cache) == 1

        cache.set("gs2", {})
        assert len(cache) == 2

        cache.invalidate("gs1")
        assert len(cache) == 1

        cache.clear()
        assert len(cache) == 0

    def test_repr(self):
        """Test string representation."""
        cache = CacheManager()
        assert repr(cache) == "CacheManager(entries=0)"

        cache.set("gs1", {})
        assert repr(cache) == "CacheManager(entries=1)"

        cache.set("gs2", {})
        assert repr(cache) == "CacheManager(entries=2)"


class TestCacheEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_cache_with_empty_dict(self):
        """Test caching an empty dictionary."""
        cache = CacheManager()
        cache.set("gs1", {})

        assert cache.get("gs1") == {}
        assert "gs1" in cache

    def test_cache_with_complex_data(self):
        """Test caching complex nested data structures."""
        cache = CacheManager()
        complex_data = {
            "id": "gs1",
            "name": "Main",
            "plants": [
                {"id": "p1", "strain": "OG Kush"},
                {"id": "p2", "strain": "Blue Dream"},
            ],
            "sensors": {
                "temperature": 72.5,
                "humidity": 55.0,
            },
            "metadata": {
                "created": "2024-01-01",
                "tags": ["indoor", "hydro"],
            },
        }

        cache.set("gs1", complex_data)
        retrieved = cache.get("gs1")

        assert retrieved == complex_data
        assert retrieved is complex_data  # Same reference

    def test_cache_independence(self):
        """Test that multiple cache instances are independent."""
        cache1 = CacheManager()
        cache2 = CacheManager()

        cache1.set("gs1", {"cache": 1})
        cache2.set("gs1", {"cache": 2})

        assert cache1.get("gs1") == {"cache": 1}
        assert cache2.get("gs1") == {"cache": 2}

        cache1.invalidate("gs1")

        assert cache1.get("gs1") is None
        assert cache2.get("gs1") == {"cache": 2}

    def test_invalidate_after_clear(self):
        """Test that invalidate works correctly after clear."""
        cache = CacheManager()
        cache.set("gs1", {"a": 1})
        cache.clear()

        # Should not raise
        cache.invalidate("gs1")

        assert len(cache) == 0


class TestCacheUsagePatterns:
    """Test realistic usage patterns."""

    def test_cache_hit_pattern(self):
        """Test typical cache hit pattern."""
        cache = CacheManager()

        # First access - cache miss
        assert cache.get("gs1") is None

        # Store data
        data = {"name": "Growspace 1"}
        cache.set("gs1", data)

        # Subsequent accesses - cache hits
        assert cache.get("gs1") is data
        assert cache.get("gs1") is data
        assert cache.get("gs1") is data

    def test_invalidation_on_update_pattern(self):
        """Test invalidation after data updates."""
        cache = CacheManager()

        # Initial cache
        cache.set("gs1", {"version": 1})
        assert cache.get("gs1") == {"version": 1}

        # Simulate data update - invalidate first
        cache.invalidate("gs1")
        assert cache.get("gs1") is None

        # Re-cache with new data
        cache.set("gs1", {"version": 2})
        assert cache.get("gs1") == {"version": 2}

    def test_bulk_operations_pattern(self):
        """Test bulk refresh pattern (clear all)."""
        cache = CacheManager()

        # Cache multiple entries
        for i in range(10):
            cache.set(f"gs{i}", {"id": i})

        assert len(cache) == 10

        # Bulk refresh - clear all
        cache.clear()

        assert len(cache) == 0

        # All entries should be gone
        for i in range(10):
            assert cache.get(f"gs{i}") is None
