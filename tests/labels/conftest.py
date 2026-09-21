"""Scaffolding for the Label Template library suites (hub issue #217).

Three things every one of them needs.

**Actors.** Authorization is the point of half these tests, so the four kinds
of caller are fixtures rather than something each test spells: an
administrator, a second administrator, an authenticated non-administrator, and
a request attributed to nobody at all.

**A library.** Built over the real `hass` and the real Home Assistant `Store`,
because the store *is* what is under test: a draft that survives a restart and
a revision that lands atomically are both claims about persistence, and a
double would prove neither. `libraries` hands out one per config entry ID,
which is also how two-entry isolation is exercised.

**A printer.** The preview tests need the printer integration's print service
to answer, and it is not installed here -- the raster in this suite is Pillow's
rather than `imagespec`'s. What is real is everything upstream of it: the same
`async_render`, the same compiler, the same safety pass and the same adapter
payload a print builds.
"""

from __future__ import annotations

import base64
from collections.abc import Callable, Iterator
from io import BytesIO
import sys
from typing import Any

from PIL import Image
import pytest

from custom_components.growspace_manager.labels.canonical import preview
from custom_components.growspace_manager.labels.canonical.diagnostics import (
    DIAGNOSTIC_CATALOGUE,
    Diagnostic,
)
from custom_components.growspace_manager.labels.library import (
    Actor,
    LabelTemplateLibrary,
)
from custom_components.growspace_manager.labels.niimbot import (
    NIIMBOT_DOMAIN,
    NIIMBOT_PRINT_SERVICE,
)
from homeassistant.core import HomeAssistant, ServiceResponse, SupportsResponse

#: The administrators and users the suites act as. Real Home Assistant user
#: IDs are opaque strings; these are too, and readable.
ADMIN = "admin-user"
OTHER_ADMIN = "other-admin-user"
VIEWER = "authenticated-user"


@pytest.fixture(autouse=True)
def diagnostics_keep_the_catalogue(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hold every diagnostic the product builds to its published catalogue.

    The card localizes by code and interpolates named parameters, so a code
    the catalogue does not declare, or a parameter, layer or severity it does
    not promise, is a translation gap -- caught here, in whichever suite made
    the product emit it. Diagnostics a test spells for itself are its own
    business and pass through.
    """
    original = Diagnostic.__init__

    def checked(self: Diagnostic, *args: Any, **kwargs: Any) -> None:
        original(self, *args, **kwargs)
        caller = sys._getframe(1).f_globals.get("__name__", "")
        if not caller.startswith("custom_components."):
            return
        spec = DIAGNOSTIC_CATALOGUE.get(self.code)
        assert spec is not None, f"{self.code} is not in DIAGNOSTIC_CATALOGUE"
        assert self.layer is spec.layer, f"{self.code} emitted at {self.layer}"
        assert self.severity in spec.severities, (
            f"{self.code} emitted as {self.severity}"
        )
        undeclared = set(self.parameters) - set(spec.parameters)
        assert not undeclared, f"{self.code} sends undeclared {sorted(undeclared)}"

    monkeypatch.setattr(Diagnostic, "__init__", checked)


#: The printer the suites print to, and the model it reports. Real device IDs
#: are registry UUIDs; the suites name their printers, so the registry lookup
#: is answered here and exercised for real in `test_printer_model_coverage`.
TESTED_MODEL = "B1"


@pytest.fixture(autouse=True)
def printers_are_the_tested_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every printer a suite names reports the model the B1 evidence covers."""
    monkeypatch.setattr(preview, "device_model", lambda _hass, _device_id: TESTED_MODEL)


@pytest.fixture
def admin() -> Actor:
    """An administrator who may manage the library."""
    return Actor(user_id=ADMIN, is_admin=True)


@pytest.fixture
def other_admin() -> Actor:
    """A second administrator, who owns none of the first one's drafts."""
    return Actor(user_id=OTHER_ADMIN, is_admin=True)


@pytest.fixture
def viewer() -> Actor:
    """An authenticated user who is not an administrator."""
    return Actor(user_id=VIEWER, is_admin=False)


@pytest.fixture
def nobody() -> Actor:
    """A request attributed to no Home Assistant user at all."""
    return Actor(user_id=None, is_admin=False)


@pytest.fixture
def libraries(hass: HomeAssistant) -> Callable[..., LabelTemplateLibrary]:
    """Return a factory for libraries, by config entry ID.

    Calling it twice with one entry ID builds two instances over the same
    stored document, which is how a restart is exercised without one.
    """

    def build(entry_id: str = "entry-a") -> LabelTemplateLibrary:
        return LabelTemplateLibrary(hass, entry_id)

    return build


@pytest.fixture
async def library(
    libraries: Callable[..., LabelTemplateLibrary],
) -> LabelTemplateLibrary:
    """One loaded, empty library for the default config entry."""
    built = libraries()
    await built.async_load()
    return built


@pytest.fixture
def printer(hass: HomeAssistant) -> Iterator[list[dict[str, Any]]]:
    """Register a stand-in for the printer integration's print service.

    Returns the list of payloads it was called with, so a test can assert that
    a preview really reached the adapter rather than being short-circuited.
    """
    calls: list[dict[str, Any]] = []

    async def handle(call: Any) -> ServiceResponse:
        calls.append(dict(call.data))
        return {"image": _one_bit_png()}

    hass.services.async_register(
        NIIMBOT_DOMAIN,
        NIIMBOT_PRINT_SERVICE,
        handle,
        supports_response=SupportsResponse.OPTIONAL,
    )
    yield calls
    hass.services.async_remove(NIIMBOT_DOMAIN, NIIMBOT_PRINT_SERVICE)


def _one_bit_png(width: int = 384, height: int = 240) -> str:
    """A monochrome PNG data URI, in the shape the renderer returns one."""
    image = Image.new("RGB", (width, height), "white")
    image.paste(Image.new("RGB", (4, 4), "black"), (1, 1))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode()}"
