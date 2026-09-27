"""Setup Presets stamp offered Setup Modules and nothing else (card#973)."""

from __future__ import annotations

import pytest
import voluptuous as vol

from custom_components.growspace_manager.domain.setup_preset import (
    SETUP_MODULES,
    SETUP_PRESETS,
    inferred_modules,
    patch_modules,
    stamp_modules,
)
from custom_components.growspace_manager.models import GrowspaceType
from custom_components.growspace_manager.schemas import (
    ADD_GROWSPACE_SCHEMA,
    UPDATE_GROWSPACE_SCHEMA,
)

# The documented effect of every preset. A preset added without a row here, or
# a row that drifts from the table, fails this suite.
_EXPECTED: dict[str, tuple[GrowspaceType, set[str]]] = {
    "simple_soil_tent": (
        GrowspaceType.FLOWER,
        {"lights", "air", "climate", "substrate"},
    ),
    "living_soil": (GrowspaceType.FLOWER, {"lights", "air", "climate", "substrate"}),
    "coco_crop_steering": (GrowspaceType.FLOWER, set(SETUP_MODULES)),
    "hydroponic_room": (
        GrowspaceType.FLOWER,
        {"lights", "air", "climate", "irrigation"},
    ),
    "mother_clone_room": (GrowspaceType.MOTHER, {"lights", "air", "climate"}),
    "drying_room": (GrowspaceType.DRY, {"air", "climate"}),
    "curing_room": (GrowspaceType.CURE, {"climate"}),
}


def test_every_preset_is_documented() -> None:
    """The table above is the preset list, no more and no less."""
    assert set(SETUP_PRESETS) == set(_EXPECTED)


@pytest.mark.parametrize(("preset", "expected"), _EXPECTED.items())
def test_preset_stamps_its_modules_and_type(
    preset: str, expected: tuple[GrowspaceType, set[str]]
) -> None:
    """Each preset offers exactly its modules and names every module."""
    growspace_type, offered = expected
    modules = stamp_modules(preset)

    assert set(modules) == set(SETUP_MODULES)
    assert {m for m, on in modules.items() if on} == offered
    assert SETUP_PRESETS[preset].growspace_type is growspace_type


def test_stamp_returns_a_fresh_map() -> None:
    """Editing one growspace's stamp cannot leak into the preset table."""
    stamp_modules("drying_room")["lights"] = True
    assert stamp_modules("drying_room")["lights"] is False


def test_unknown_preset_raises() -> None:
    """A preset nobody declared is a programming error, not an empty stamp."""
    with pytest.raises(KeyError):
        stamp_modules("greenhouse")


@pytest.mark.parametrize(
    ("growspace_id", "preset"),
    [
        ("mother", "mother_clone_room"),
        ("clone", "mother_clone_room"),
        ("dry", "drying_room"),
        ("cure", "curing_room"),
    ],
)
def test_canonical_growspaces_infer_their_room(growspace_id: str, preset: str) -> None:
    """The canonical growspaces were never stamped but their room is known."""
    assert inferred_modules(growspace_id) == stamp_modules(preset)


def test_ordinary_growspace_infers_nothing() -> None:
    """A user growspace without a stamp stays unstamped."""
    assert inferred_modules("4f1c") is None


def test_patch_merges_over_the_stamp() -> None:
    """A partial edit changes only the modules it names."""
    patched = patch_modules(stamp_modules("simple_soil_tent"), {"irrigation": True})

    assert patched == {**stamp_modules("simple_soil_tent"), "irrigation": True}


def test_patch_over_an_unstamped_set_starts_from_everything_offered() -> None:
    """Unstamped means every module is offered, so a patch starts there."""
    patched = patch_modules(None, {"lights": False})

    assert patched == {**dict.fromkeys(SETUP_MODULES, True), "lights": False}


def test_patch_refuses_an_unknown_module() -> None:
    """Only declared modules can be edited."""
    with pytest.raises(ValueError, match="Unknown setup module"):
        patch_modules(None, {"co2": True})


def test_update_schema_accepts_preset_and_partial_modules() -> None:
    """The service takes a preset stamp and a partial module edit."""
    data = UPDATE_GROWSPACE_SCHEMA(
        {
            "growspace_id": "gs1",
            "setup_preset": "drying_room",
            "setup_modules": {"lights": True},
        }
    )

    assert data["setup_preset"] == "drying_room"
    assert data["setup_modules"] == {"lights": True}


@pytest.mark.parametrize(
    "payload",
    [
        {"setup_preset": "greenhouse"},
        {"setup_modules": {"co2": True}},
    ],
)
def test_update_schema_refuses_undeclared_presets_and_modules(payload) -> None:
    """A preset or module the integration does not know is refused at the door."""
    with pytest.raises(vol.Invalid):
        UPDATE_GROWSPACE_SCHEMA({"growspace_id": "gs1", **payload})


def test_add_schema_accepts_a_preset() -> None:
    """A growspace added from the card can be created with a preset."""
    data = ADD_GROWSPACE_SCHEMA(
        {"name": "Tent", "rows": 2, "plants_per_row": 2, "setup_preset": "living_soil"}
    )

    assert data["setup_preset"] == "living_soil"
