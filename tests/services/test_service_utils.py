"""Tests for shared service utilities."""

from unittest.mock import MagicMock

import pytest

from custom_components.growspace_manager.exceptions import GrowspaceError
from custom_components.growspace_manager.services.utils import (
    get_validated_coordinator,
    handle_service_errors,
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


async def test_handle_service_errors_generic_exception(caplog):
    """Test handle_service_errors handles generic exceptions."""

    @handle_service_errors
    async def error_func():
        raise ValueError("Generic error")

    with pytest.raises(ServiceValidationError, match="Operation failed: Generic error"):
        await error_func()

    assert "Unexpected error in error_func" in caplog.text
