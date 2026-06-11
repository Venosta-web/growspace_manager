"""Guard test for the Service Facade seam.

The coordinator's collaborators are private (``coordinator._data_repository``,
``coordinator._plant_manager``, ...). Only the coordinator itself and the
service facade layer (``services/``) may read them; every other caller must go
through ``coordinator.services.*``.

See ``custom_components/growspace_manager/CONTEXT.md`` -> "Seam Enforcement".
"""

from __future__ import annotations

from pathlib import Path
import re

import custom_components.growspace_manager as gm_pkg

# Private coordinator collaborators that must not be reached from outside the seam.
_SEALED_INTERNALS = (
    "data_repository",
    "plant_manager",
    "growspace_manager",
    "nutrient_manager",
    "genetics_manager",
    "subsystem_manager",
    "strain_library",
    "notification_manager",
)

# Access via a coordinator reference: ``coordinator._x``, ``self.coordinator._x``,
# ``self._coordinator._x`` all end in ``coordinator._<name>``. Also catch the
# public form (``coordinator.<name>``) in case a forwarding alias is re-added,
# and the ``entry.runtime_data.<name>`` alias (runtime_data *is* the coordinator).
_NAMES = "|".join(_SEALED_INTERNALS)
_BYPASS_RE = re.compile(rf"(?:coordinator|runtime_data)\._?(?:{_NAMES})\b")

# The only sanctioned readers of coordinator internals.
_EXEMPT_DIRS = ("services",)
_EXEMPT_FILES = ("coordinator.py",)


def test_no_external_access_to_coordinator_internals() -> None:
    """Fail if any module outside the seam reaches a private coordinator collaborator."""
    package_root = Path(gm_pkg.__file__).parent
    offenders: list[str] = []

    for path in package_root.rglob("*.py"):
        rel = path.relative_to(package_root)
        if rel.parts[0] in _EXEMPT_DIRS or rel.name in _EXEMPT_FILES:
            continue
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if _BYPASS_RE.search(line):
                offenders.append(f"{rel}:{lineno}: {line.strip()}")

    assert not offenders, (
        "Coordinator internals must be reached through coordinator.services.* "
        "(see CONTEXT.md 'Seam Enforcement'). Offending lines:\n"
        + "\n".join(offenders)
    )
