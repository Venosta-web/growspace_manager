"""The global [[Irrigation Program]] library.

Programs are global for the same reason the [[Irrigation Recipe]]s they
reference are: a plan authored for one tent is the plan a grower wants to bind
to the next one (ADR-0045). The library owns storage and identity;
``domain/irrigation_program.py`` owns what a program's slots mean.

Nothing here resolves a ``recipe_id`` against the recipe library. A program
holds recipes **by reference**, and deleting a recipe leaves empty slots rather
than cascading or being refused — so a slot naming a recipe that is not there
is a [[Program Hold]], not a storage error. Validating existence at save time
would additionally make re-saving an untouched program fail because of a
deletion elsewhere in it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping
import logging
from typing import Any
import uuid

from custom_components.growspace_manager.domain.irrigation_program import (
    ProgramError,
    build_program_slots,
)
from custom_components.growspace_manager.exceptions import EntityNotFoundError
from custom_components.growspace_manager.models.irrigation_program import (
    IrrigationProgram,
)
import homeassistant.util.dt as dt_util

_LOGGER = logging.getLogger(__name__)


class IrrigationProgramLibrary:
    """Stores, lists and removes grower-authored Irrigation Programs."""

    def __init__(self, save_callback: Callable[[], Awaitable[None]]) -> None:
        """Initialise the library over the coordinator's save callback."""
        self.save_callback = save_callback
        self.programs: dict[str, IrrigationProgram] = {}

    def load_data(self, programs: dict[str, IrrigationProgram]) -> None:
        """Replace the library contents (called by StorageManager on load)."""
        self.programs = programs

    async def async_save_program(
        self,
        name: str,
        slots: Iterable[Mapping[str, Any]],
        program_id: str | None = None,
    ) -> IrrigationProgram:
        """Save a named plan of ``(stage, week)`` slots.

        The whole slot list is validated before anything is stored, so a
        refused save leaves the library exactly as it was — and a save that
        does land replaces the plan wholesale rather than merging into it, an
        ordered plan being the thing a grower edits as a whole.

        Raises:
            ProgramError: when the slots cannot become a plan.
        """
        stripped = name.strip()
        if not stripped:
            raise ProgramError("A program's name cannot be blank.")
        built = build_program_slots(slots)

        existing = self.programs.get(program_id) if program_id else None
        program = IrrigationProgram(
            id=program_id or str(uuid.uuid4()),
            name=stripped,
            slots=built,
            created_at=existing.created_at
            if existing is not None
            else dt_util.utcnow().isoformat(),
        )
        self.programs[program.id] = program

        await self.save_callback()
        _LOGGER.info(
            "Saved irrigation program '%s' with %d slot(s) (id=%s)",
            program.name,
            len(program.slots),
            program.id,
        )
        return program

    def get_program(self, program_id: str) -> IrrigationProgram:
        """Return one program by id.

        Hands out the library's own object rather than a copy, matching the
        recipe library: a program is held by reference wherever it is used.

        Raises:
            EntityNotFoundError: when no program carries that id.
        """
        program = self.programs.get(program_id)
        if program is None:
            raise EntityNotFoundError(f"Irrigation program '{program_id}' not found")
        return program

    async def async_remove_program(self, program_id: str) -> None:
        """Remove a program from the library.

        A growspace bound to it keeps its ``irrigation_program_id``, exactly as
        a growspace keeps the ``applied_recipe_id`` of a deleted recipe: the
        removal does not reach into every growspace, and a binding that names
        nothing reads as no current slot rather than as an error.

        Raises:
            EntityNotFoundError: when no program carries that id.
        """
        program = self.programs.pop(program_id, None)
        if program is None:
            raise EntityNotFoundError(f"Irrigation program '{program_id}' not found")

        await self.save_callback()
        _LOGGER.info(
            "Removed irrigation program '%s' (id=%s)", program.name, program_id
        )

    def serialized_programs(self) -> dict[str, dict[str, Any]]:
        """Return the library keyed by program id, ready for the wire."""
        return {pid: program.to_dict() for pid, program in self.programs.items()}

    def get_serialization_data(self) -> dict[str, Any]:
        """Return the library under the key the config document stores it at."""
        return {"irrigation_programs": self.serialized_programs()}


__all__ = ["IrrigationProgramLibrary", "ProgramError"]
