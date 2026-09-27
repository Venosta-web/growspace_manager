"""Setup Presets and the Setup Modules they stamp (card#973).

A Setup Preset describes what kind of room a growspace is — a soil tent, a
drying room — and exists to decide which subsystems the card's setup checklist
offers. Choosing one **stamps** the growspace's Setup Modules once, the way a
Steering Mode stamps its setpoints (ADR-0012): the modules are then ordinary
editable flags, the preset decays into a label, and re-choosing a preset
re-stamps, discarding hand edits. A preset never writes a cultivation target.

The module's *role* is not the preset's business. Lights and air are core,
climate, irrigation and substrate optional, whatever the room — a preset only
decides whether each is offered at all.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from custom_components.growspace_manager.models.growspace import GrowspaceType

SETUP_MODULES: tuple[str, ...] = ("lights", "air", "climate", "irrigation", "substrate")


@dataclass(frozen=True, slots=True)
class SetupPreset:
    """One preset: the growspace type it creates, and the modules it offers."""

    growspace_type: GrowspaceType
    offered: frozenset[str]

    def modules(self) -> dict[str, bool]:
        """Return the full module map this preset stamps."""
        return {module: module in self.offered for module in SETUP_MODULES}


SETUP_PRESETS: dict[str, SetupPreset] = {
    "simple_soil_tent": SetupPreset(
        GrowspaceType.FLOWER, frozenset({"lights", "air", "climate", "substrate"})
    ),
    "living_soil": SetupPreset(
        GrowspaceType.FLOWER, frozenset({"lights", "air", "climate", "substrate"})
    ),
    "coco_crop_steering": SetupPreset(GrowspaceType.FLOWER, frozenset(SETUP_MODULES)),
    "hydroponic_room": SetupPreset(
        GrowspaceType.FLOWER, frozenset({"lights", "air", "climate", "irrigation"})
    ),
    "mother_clone_room": SetupPreset(
        GrowspaceType.MOTHER, frozenset({"lights", "air", "climate"})
    ),
    "drying_room": SetupPreset(GrowspaceType.DRY, frozenset({"air", "climate"})),
    "curing_room": SetupPreset(GrowspaceType.CURE, frozenset({"climate"})),
}

# The canonical growspaces predate presets and are never created through one,
# but what kind of room each is has never been in doubt.
_CANONICAL_PRESETS: dict[str, str] = {
    "mother": "mother_clone_room",
    "clone": "mother_clone_room",
    "dry": "drying_room",
    "cure": "curing_room",
}


def stamp_modules(preset: str) -> dict[str, bool]:
    """Return the Setup Modules ``preset`` stamps; unknown presets raise KeyError."""
    return SETUP_PRESETS[preset].modules()


def inferred_modules(growspace_id: str) -> dict[str, bool] | None:
    """Return the modules a never-stamped canonical growspace implies, else None."""
    preset = _CANONICAL_PRESETS.get(growspace_id)
    return stamp_modules(preset) if preset else None


def patch_modules(
    current: Mapping[str, bool] | None, patch: Mapping[str, bool]
) -> dict[str, bool]:
    """Merge a partial module edit over ``current``; an unstamped set offers all."""
    base = dict(current) if current else dict.fromkeys(SETUP_MODULES, True)
    for module, offered in patch.items():
        if module not in SETUP_MODULES:
            raise ValueError(f"Unknown setup module: {module}")
        base[module] = bool(offered)
    return base
