"""Tests for get_conversation_threads and save_conversation_threads WebSocket handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.websocket.ai_assistant import (
    SCHEMA_WS_GET_CONVERSATION_THREADS,
    SCHEMA_WS_SAVE_CONVERSATION_THREADS,
    WS_TYPE_GET_CONVERSATION_THREADS,
    WS_TYPE_SAVE_CONVERSATION_THREADS,
    websocket_get_conversation_threads,
    websocket_save_conversation_threads,
)


@pytest.fixture
def mock_connection() -> MagicMock:
    conn = MagicMock()
    conn.send_result = MagicMock()
    conn.send_error = MagicMock()
    return conn


def _make_coordinator(threads: list | None = None) -> MagicMock:
    coord = MagicMock()
    store = MagicMock()
    store.get_threads = MagicMock(return_value=threads or [])
    store.save_threads = AsyncMock(return_value=None)
    coord.conversation_store = store
    return coord


_SAMPLE_THREADS = [
    {
        "thread_id": "t1",
        "growspace_id": "gs1",
        "messages": [],
        "pinned": True,
        "updated_at": 1700000001,
    },
    {
        "thread_id": "t2",
        "growspace_id": "gs1",
        "messages": [],
        "pinned": False,
        "updated_at": 1700000000,
    },
]

# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_get_schema_requires_growspace_id() -> None:
    """get_conversation_threads schema requires growspace_id."""
    msg = {"id": 1, "type": WS_TYPE_GET_CONVERSATION_THREADS, "growspace_id": "gs1"}
    validated = SCHEMA_WS_GET_CONVERSATION_THREADS(msg)
    assert validated["growspace_id"] == "gs1"


def test_get_schema_rejects_missing_growspace_id() -> None:
    """get_conversation_threads schema rejects missing growspace_id."""
    import voluptuous as vol

    msg = {"id": 1, "type": WS_TYPE_GET_CONVERSATION_THREADS}
    with pytest.raises(vol.Invalid):
        SCHEMA_WS_GET_CONVERSATION_THREADS(msg)


def test_save_schema_requires_growspace_id_and_threads() -> None:
    """save_conversation_threads schema requires growspace_id and threads."""
    msg = {
        "id": 1,
        "type": WS_TYPE_SAVE_CONVERSATION_THREADS,
        "growspace_id": "gs1",
        "threads": _SAMPLE_THREADS,
    }
    validated = SCHEMA_WS_SAVE_CONVERSATION_THREADS(msg)
    assert validated["growspace_id"] == "gs1"
    assert len(validated["threads"]) == 2


def test_save_schema_accepts_empty_thread_list() -> None:
    """save_conversation_threads accepts an empty threads list."""
    msg = {
        "id": 1,
        "type": WS_TYPE_SAVE_CONVERSATION_THREADS,
        "growspace_id": "gs1",
        "threads": [],
    }
    validated = SCHEMA_WS_SAVE_CONVERSATION_THREADS(msg)
    assert validated["threads"] == []


# ---------------------------------------------------------------------------
# get_conversation_threads handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_conversation_threads_returns_threads(
    mock_connection: MagicMock,
) -> None:
    """Handler returns threads from the conversation store for the given growspace."""
    coordinator = _make_coordinator(_SAMPLE_THREADS)
    msg = {"id": 1, "type": WS_TYPE_GET_CONVERSATION_THREADS, "growspace_id": "gs1"}

    result = await websocket_get_conversation_threads(MagicMock(), coordinator, msg)

    assert result == _SAMPLE_THREADS
    coordinator.conversation_store.get_threads.assert_called_once_with("gs1")


@pytest.mark.asyncio
async def test_get_conversation_threads_returns_empty_list_when_none(
    mock_connection: MagicMock,
) -> None:
    """Handler returns an empty list when no threads exist for the growspace."""
    coordinator = _make_coordinator([])
    msg = {"id": 1, "type": WS_TYPE_GET_CONVERSATION_THREADS, "growspace_id": "new-gs"}

    result = await websocket_get_conversation_threads(MagicMock(), coordinator, msg)

    assert result == []


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_save_conversation_threads_persists_threads(
    mock_connection: MagicMock,
) -> None:
    """Handler calls save_threads with the correct growspace_id and thread list."""
    coordinator = _make_coordinator()
    msg = {
        "id": 2,
        "type": WS_TYPE_SAVE_CONVERSATION_THREADS,
        "growspace_id": "gs1",
        "threads": _SAMPLE_THREADS,
    }

    result = await websocket_save_conversation_threads(MagicMock(), coordinator, msg)

    coordinator.conversation_store.save_threads.assert_awaited_once_with(
        "gs1", _SAMPLE_THREADS
    )
    assert result == {"success": True}


@pytest.mark.asyncio
async def test_save_conversation_threads_accepts_empty_list(
    mock_connection: MagicMock,
) -> None:
    """Handler accepts an empty thread list (clears threads for a growspace)."""
    coordinator = _make_coordinator()
    msg = {
        "id": 3,
        "type": WS_TYPE_SAVE_CONVERSATION_THREADS,
        "growspace_id": "gs1",
        "threads": [],
    }

    result = await websocket_save_conversation_threads(MagicMock(), coordinator, msg)

    coordinator.conversation_store.save_threads.assert_awaited_once_with("gs1", [])
    assert result == {"success": True}
