"""Unit tests for ConversationStore."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.conversation_store import ConversationStore


def _make_store(persisted: dict | None = None) -> tuple[ConversationStore, MagicMock]:
    """Return a ConversationStore and its underlying mock HA Store."""
    mock_ha_store = MagicMock()
    mock_ha_store.async_load = AsyncMock(return_value=persisted)
    mock_ha_store.async_save = AsyncMock(return_value=None)
    return ConversationStore(mock_ha_store), mock_ha_store


_THREAD_A = {
    "thread_id": "t1",
    "growspace_id": "gs1",
    "messages": [],
    "pinned": True,
    "updated_at": 1700000001,
}
_THREAD_B = {
    "thread_id": "t2",
    "growspace_id": "gs1",
    "messages": [],
    "pinned": False,
    "updated_at": 1700000000,
}


@pytest.mark.asyncio
async def test_async_load_hydrates_threads() -> None:
    """async_load populates in-memory data from the store."""
    store, _ = _make_store({"threads_by_growspace": {"gs1": [_THREAD_A, _THREAD_B]}})

    await store.async_load()

    assert store.get_threads("gs1") == [_THREAD_A, _THREAD_B]


@pytest.mark.asyncio
async def test_async_load_handles_empty_store() -> None:
    """async_load with no persisted data returns empty threads."""
    store, _ = _make_store(None)

    await store.async_load()

    assert store.get_threads("gs1") == []


@pytest.mark.asyncio
async def test_get_threads_returns_empty_list_for_unknown_growspace() -> None:
    """get_threads returns [] for a growspace with no threads."""
    store, _ = _make_store(None)
    await store.async_load()

    result = store.get_threads("unknown-gs")

    assert result == []


@pytest.mark.asyncio
async def test_save_threads_replaces_and_persists() -> None:
    """save_threads replaces the growspace thread list and calls async_save."""
    store, mock_ha_store = _make_store({"threads_by_growspace": {"gs1": [_THREAD_A]}})
    await store.async_load()

    await store.save_threads("gs1", [_THREAD_B])

    assert store.get_threads("gs1") == [_THREAD_B]
    mock_ha_store.async_save.assert_called_once_with(
        {"threads_by_growspace": {"gs1": [_THREAD_B]}}
    )


@pytest.mark.asyncio
async def test_save_threads_does_not_overwrite_other_growspaces() -> None:
    """save_threads for gs1 leaves gs2 threads unchanged."""
    gs2_thread = {**_THREAD_A, "thread_id": "t3", "growspace_id": "gs2"}
    store, _ = _make_store(
        {"threads_by_growspace": {"gs1": [_THREAD_A], "gs2": [gs2_thread]}}
    )
    await store.async_load()

    await store.save_threads("gs1", [_THREAD_B])

    assert store.get_threads("gs2") == [gs2_thread]


@pytest.mark.asyncio
async def test_save_threads_accepts_empty_list() -> None:
    """save_threads with [] clears the growspace thread list."""
    store, mock_ha_store = _make_store({"threads_by_growspace": {"gs1": [_THREAD_A]}})
    await store.async_load()

    await store.save_threads("gs1", [])

    assert store.get_threads("gs1") == []
    mock_ha_store.async_save.assert_called_once()
