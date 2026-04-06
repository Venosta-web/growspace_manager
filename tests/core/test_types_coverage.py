"""Coverage tests for types.py."""

from custom_components.growspace_manager.integration_types import (
    is_growspace_data,
    is_plant_data,
)


def test_is_plant_data() -> None:
    """Test is_plant_data type guard."""
    # Valid data
    valid_data = {"plant_id": "p1", "growspace_id": "gs1", "other": "value"}
    assert is_plant_data(valid_data) is True

    # Invalid data - missing plant_id
    invalid_data_1 = {"growspace_id": "gs1"}
    assert is_plant_data(invalid_data_1) is False

    # Invalid data - missing growspace_id
    invalid_data_2 = {"plant_id": "p1"}
    assert is_plant_data(invalid_data_2) is False

    # Invalid data - missing both
    invalid_data_3 = {"other": "value"}
    assert is_plant_data(invalid_data_3) is False


def test_is_growspace_data() -> None:
    """Test is_growspace_data type guard."""
    # Valid data
    valid_data = {"id": "gs1", "name": "Test GS", "other": "value"}
    assert is_growspace_data(valid_data) is True

    # Invalid data - missing id
    invalid_data_1 = {"name": "Test GS"}
    assert is_growspace_data(invalid_data_1) is False

    # Invalid data - missing name
    invalid_data_2 = {"id": "gs1"}
    assert is_growspace_data(invalid_data_2) is False

    # Invalid data - missing both
    invalid_data_3 = {"other": "value"}
    assert is_growspace_data(invalid_data_3) is False
