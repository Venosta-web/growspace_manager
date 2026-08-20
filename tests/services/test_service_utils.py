"""Tests for shared service utilities."""

from typing import Any
from unittest.mock import MagicMock

import pytest

from custom_components.growspace_manager.cache.cache_manager import CacheManager
from custom_components.growspace_manager.exceptions import GrowspaceError
from custom_components.growspace_manager.services.utils import (
    get_validated_coordinator,
    handle_service_errors,
    invalidates_cache,
)
from homeassistant.exceptions import ServiceValidationError


async def test_get_validated_coordinator_none():
    """Test get_validated_coordinator with None entry."""
    with pytest.raises(ServiceValidationError, match="Coordinator not available"):
        get_validated_coordinator(None)


async def test_get_validated_coordinator_no_runtime_data():
    """Test get_validated_coordinator with no runtime data."""
    mock_entry = MagicMock()
    mock_entry.runtime_data = None
    with pytest.raises(ServiceValidationError, match="Coordinator not available"):
        get_validated_coordinator(mock_entry)


async def test_get_validated_coordinator_success():
    """Test get_validated_coordinator success case."""
    mock_entry = MagicMock()
    mock_coordinator = MagicMock()
    mock_entry.runtime_data = mock_coordinator
    assert get_validated_coordinator(mock_entry) == mock_coordinator


async def test_handle_service_errors_success():
    """Test handle_service_errors success case."""

    @handle_service_errors
    async def success_func():
        return "success"

    assert await success_func() == "success"


async def test_handle_service_errors_re_raise():
    """Test handle_service_errors re-raises ServiceValidationError."""

    @handle_service_errors
    async def error_func():
        raise ServiceValidationError("Existing error")

    with pytest.raises(ServiceValidationError, match="Existing error"):
        await error_func()


async def test_handle_service_errors_growspace_error():
    """Test handle_service_errors converts GrowspaceError."""

    @handle_service_errors
    async def error_func():
        raise GrowspaceError("Domain error")

    with pytest.raises(ServiceValidationError, match="Domain error"):
        await error_func()


async def test_handle_service_errors_generic_exception(
    caplog: pytest.LogCaptureFixture,
):
    """Test handle_service_errors handles generic exceptions."""

    @handle_service_errors
    async def error_func():
        raise ValueError("Generic error")

    with pytest.raises(ServiceValidationError, match="Operation failed: Generic error"):
        await error_func()

    assert "Unexpected error in error_func" in caplog.text


async def test_invalidates_cache_kwarg() -> None:
    """Test invalidates_cache with growspace_id in kwargs."""
    mock_coordinator = MagicMock()
    mock_coordinator.cache = CacheManager()
    mock_coordinator.cache.set("growspace_1", {"data": "data"})

    @invalidates_cache()
    async def mock_mutation(coordinator: Any, growspace_id: str | None = None) -> str:
        return "mutated"

    result = await mock_mutation(mock_coordinator, growspace_id="growspace_1")
    assert result == "mutated"
    assert "growspace_1" not in mock_coordinator.cache


async def test_invalidates_cache_args_dict() -> None:
    """Test invalidates_cache with growspace_id in args[1] dictionary."""
    mock_coordinator = MagicMock()
    mock_coordinator.cache = CacheManager()
    mock_coordinator.cache.set("growspace_1", {"data": "data"})

    @invalidates_cache()
    async def mock_mutation(coordinator: Any, call_data: dict[str, Any]) -> str:
        return "mutated"

    result = await mock_mutation(mock_coordinator, {"growspace_id": "growspace_1"})
    assert result == "mutated"
    assert "growspace_1" not in mock_coordinator.cache


async def test_invalidates_cache_custom_kwarg() -> None:
    """Test invalidates_cache with a custom kwarg name."""
    mock_coordinator = MagicMock()
    mock_coordinator.cache = CacheManager()
    mock_coordinator.cache.set("growspace_1", {"data": "data"})

    @invalidates_cache("custom_id")
    async def mock_mutation(coordinator: Any, custom_id: str | None = None) -> str:
        return "mutated"

    result = await mock_mutation(mock_coordinator, custom_id="growspace_1")
    assert result == "mutated"
    assert "growspace_1" not in mock_coordinator.cache


async def test_invalidates_cache_missing_id() -> None:
    """Test invalidates_cache when no growspace_id is provided."""
    mock_coordinator = MagicMock()
    mock_coordinator.cache = CacheManager()
    mock_coordinator.cache.set("growspace_1", {"data": "data"})

    @invalidates_cache()
    async def mock_mutation(coordinator: Any) -> str:
        return "mutated"

    result = await mock_mutation(mock_coordinator)
    assert result == "mutated"
    assert "growspace_1" in mock_coordinator.cache


async def test_invalidates_cache_attribute_error() -> None:
    """Test invalidates_cache handles AttributeError when coordinator lacks cache."""
    mock_coordinator = object()  # Has no cache attribute

    @invalidates_cache()
    async def mock_mutation(coordinator: Any, growspace_id: str | None = None) -> str:
        return "mutated"

    result = await mock_mutation(mock_coordinator, growspace_id="growspace_1")
    assert result == "mutated"


async def test_invalidates_cache_index_error() -> None:
    """Test invalidates_cache handles IndexError when args is empty."""

    @invalidates_cache()
    async def mock_mutation(**kwargs: Any) -> str:
        return "mutated"

    result = await mock_mutation(growspace_id="growspace_1")
    assert result == "mutated"
