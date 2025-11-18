import pytest
from datetime import date
from homeassistant.exceptions import HomeAssistantError

from custom_components.growspace_manager.const import (
    ADD_GROWSPACE_SCHEMA,
    REMOVE_GROWSPACE_SCHEMA,
    ADD_PLANT_SCHEMA,
    UPDATE_PLANT_SCHEMA,
    REMOVE_PLANT_SCHEMA,
    MOVE_PLANT_SCHEMA,
    SWITCH_PLANT_SCHEMA,
    TRANSITION_PLANT_SCHEMA,
    MOVE_CLONE_SCHEMA,
    EXPORT_STRAIN_LIBRARY_SCHEMA,
    IMPORT_STRAIN_LIBRARY_SCHEMA,
    CLEAR_STRAIN_LIBRARY_SCHEMA,
    HARVEST_PLANT_SCHEMA,
    TAKE_CLONE_SCHEMA,
    DEBUG_CLEANUP_LEGACY_SCHEMA,
    DEBUG_LIST_GROWSPACES_SCHEMA,
    DEBUG_RESET_SPECIAL_GROWSPACES_SCHEMA,
    DEBUG_CONSOLIDATE_DUPLICATE_SPECIAL_SCHEMA,
)


def test_add_growspace_schema_valid():
    data = {"name": "Test GS", "rows": 3, "plants_per_row": 3}
    validated = ADD_GROWSPACE_SCHEMA(data)
    assert validated == data


def test_add_growspace_schema_invalid():
    data = {"name": "Test GS", "rows": -1, "plants_per_row": 3}
    with pytest.raises(Exception):
        services.ADD_GROWSPACE_SCHEMA(data)


def test_remove_growspace_schema_valid():
    data = {"growspace_id": "gs1"}
    assert REMOVE_GROWSPACE_SCHEMA(data) == data


def test_add_plant_schema_valid():
    data = {
        "growspace_id": "gs1",
        "strain": "OG",
        "row": 1,
        "col": 1,
        "phenotype": "A",
        "seedling_start": date.today(),
    }
    validated = ADD_PLANT_SCHEMA(data)
    assert validated == data


def test_add_plant_schema_invalid():
    data = {"growspace_id": "gs1", "strain": "OG", "row": -1, "col": 1}
    with pytest.raises(Exception):
        ADD_PLANT_SCHEMA(data)


def test_update_plant_schema_valid():
    data = {"plant_id": "p1", "strain": "OG"}
    validated = UPDATE_PLANT_SCHEMA(data)
    assert validated["plant_id"] == "p1"


def test_remove_plant_schema_valid():
    data = {"plant_id": "p1"}
    assert REMOVE_PLANT_SCHEMA(data) == data


def test_move_plant_schema_valid():
    data = {"plant_id": "p1", "new_row": 2, "new_col": 3}
    assert MOVE_PLANT_SCHEMA(data) == data


def test_switch_plant_schema_valid():
    data = {"plant_id_1": "p1", "plant_id_2": "p2"}
    assert SWITCH_PLANT_SCHEMA(data) == data


def test_transition_plant_schema_valid():
    data = {"plant_id": "p1", "new_stage": "veg", "transition_date": date.today()}
    assert TRANSITION_PLANT_SCHEMA(data) == data


def test_move_clone_schema_valid():
    data = {"plant_id": "p1", "target_growspace_id": "gs2"}
    assert MOVE_CLONE_SCHEMA(data) == data


def test_export_strain_library_schema_valid():
    data = {}
    assert EXPORT_STRAIN_LIBRARY_SCHEMA(data) == data


def test_import_strain_library_schema_valid():
    data = {"strains": ["A", "B"], "replace": True}
    validated = IMPORT_STRAIN_LIBRARY_SCHEMA(data)
    assert validated["replace"] is True


def test_clear_strain_library_schema_valid():
    data = {}
    assert CLEAR_STRAIN_LIBRARY_SCHEMA(data) == data


def test_harvest_plant_schema_valid():
    data = {
        "plant_id": "p1",
        "target_growspace_id": "gs2",
        "transition_date": date.today(),
    }
    assert HARVEST_PLANT_SCHEMA(data) == data


def test_take_clone_schema_valid():
    data = {"mother_plant_id": "p1", "num_clones": 2}
    validated = TAKE_CLONE_SCHEMA(data)
    assert validated["num_clones"] == 2


def test_debug_cleanup_legacy_schema_valid():
    data = {"dry_only": True, "cure_only": False}
    validated = DEBUG_CLEANUP_LEGACY_SCHEMA(data)
    assert validated["dry_only"] is True


def test_debug_list_growspaces_schema_valid():
    assert DEBUG_LIST_GROWSPACES_SCHEMA({}) == {}


def test_debug_reset_special_growspaces_schema_valid():
    data = {"reset_dry": True, "reset_cure": False, "preserve_plants": True}
    validated = DEBUG_RESET_SPECIAL_GROWSPACES_SCHEMA(data)
    assert validated["reset_cure"] is False


def test_debug_consolidate_duplicate_special_schema_valid():
    assert DEBUG_CONSOLIDATE_DUPLICATE_SPECIAL_SCHEMA({}) == {}
