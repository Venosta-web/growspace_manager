"""The wire an editor edits through: open, autosave, preview, publish, discard.

Issue #225. The draft lifecycle has been in the library since #217; these are
the claims the six commands on top of it make.

Three of them carry the whole ticket. A refusal is a **result**, so an editor
can tell "somebody saved over you" from "this does not validate yet" from "you
are not an administrator" and do something different about each. Opening
**resumes**, so a reload, a reconnect or a second client comes back to the work
rather than replacing it. And a preview may only settle the geometry it
actually rendered, so a raster can never look current over a layout it does not
show.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from types import SimpleNamespace
from typing import Any

from freezegun import freeze_time
import pytest

from custom_components.growspace_manager.labels.canonical import (
    CAPABILITY_GENERATION,
    LABEL_SIZES,
    PROFILES,
    factory_template_for_size,
)
from custom_components.growspace_manager.labels.capability import (
    CAPABILITY_FAMILY,
    contract_identity,
)
from custom_components.growspace_manager.labels.library import (
    FACTORY,
    LabelTemplateLibrary,
    async_get_library,
)
from custom_components.growspace_manager.websocket import drafts
from custom_components.growspace_manager.websocket._common import WS_MSG_USER
from homeassistant.core import HomeAssistant

from .conftest import ADMIN, OTHER_ADMIN, VIEWER

#: The one stock a shipped Capability Profile can render, and therefore the
#: only one a draft preview can answer for.
PROFILED_SIZE = next(iter(PROFILES.values())).label_size_id
UNPROFILED_SIZE = next(
    size_id
    for size_id in LABEL_SIZES
    if not any(profile.label_size_id == size_id for profile in PROFILES.values())
)
FACTORY_FOR_PROFILED_SIZE = factory_template_for_size(PROFILED_SIZE).id

ENTRY_ID = "entry-a"

#: A stand-in for the coordinator. These commands resolve `any` and use it for
#: exactly one thing -- naming the config entry whose library to open.
COORDINATOR = SimpleNamespace(config_entry=SimpleNamespace(entry_id=ENTRY_ID))


def _user(user_id: str | None, *, is_admin: bool) -> Any:
    """One acting identity, in the shape `Actor.from_user` reads."""
    if user_id is None:
        return None
    return SimpleNamespace(id=user_id, is_admin=is_admin)


ADMIN_USER = _user(ADMIN, is_admin=True)
OTHER_ADMIN_USER = _user(OTHER_ADMIN, is_admin=True)
VIEWER_USER = _user(VIEWER, is_admin=False)


def _message(user: Any = ADMIN_USER, **overrides: Any) -> dict[str, Any]:
    """One command message, contract-gated and attributed."""
    message: dict[str, Any] = {"contract": contract_identity(), WS_MSG_USER: user}
    message.update(overrides)
    return message


async def _open(
    hass: HomeAssistant, *, user: Any = ADMIN_USER, **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {"label_size_id": PROFILED_SIZE}
    payload.update(overrides)
    return await drafts.websocket_open_label_template_draft(
        hass, COORDINATOR, _message(user, **payload)
    )


async def _autosave(
    hass: HomeAssistant, *, user: Any = ADMIN_USER, **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {"label_size_id": PROFILED_SIZE}
    payload.update(overrides)
    return await drafts.websocket_autosave_label_template_draft(
        hass, COORDINATOR, _message(user, **payload)
    )


async def _preview(
    hass: HomeAssistant, *, user: Any = ADMIN_USER, **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "label_size_id": PROFILED_SIZE,
        "context": "strain",
        "fixture_family": "typical",
        "density": "normal",
        "locale": "en",
    }
    payload.update(overrides)
    return await drafts.websocket_preview_label_template_draft(
        hass, COORDINATOR, _message(user, **payload)
    )


async def _publish(
    hass: HomeAssistant, *, user: Any = ADMIN_USER, **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {"label_size_id": PROFILED_SIZE}
    payload.update(overrides)
    return await drafts.websocket_publish_label_template_draft(
        hass, COORDINATOR, _message(user, **payload)
    )


async def _discard(
    hass: HomeAssistant, *, user: Any = ADMIN_USER, **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {"label_size_id": PROFILED_SIZE}
    payload.update(overrides)
    return await drafts.websocket_discard_label_template_draft(
        hass, COORDINATOR, _message(user, **payload)
    )


async def _snapshot(
    hass: HomeAssistant, *, user: Any = ADMIN_USER, **overrides: Any
) -> dict[str, Any]:
    return await drafts.websocket_get_label_template_library(
        hass, COORDINATOR, _message(user, **overrides)
    )


async def _entry_library(hass: HomeAssistant) -> LabelTemplateLibrary:
    """The same library instance the handlers reach."""
    return await async_get_library(hass, ENTRY_ID)


def _moved(document: dict[str, Any], *, x_mm: float) -> dict[str, Any]:
    """Return the document with its first element moved, as an editor would."""
    edited = json.loads(json.dumps(document))
    edited["elements"][0]["frame"]["x_mm"] = x_mm
    return edited


# ---------------------------------------------------------------------------
# Registration, and the gate above every one of them
# ---------------------------------------------------------------------------


def test_the_six_editing_commands_are_registered_with_the_acting_user() -> None:
    """Every one of them needs to know who is asking, and says so declaratively."""
    assert [command.type for command in drafts.COMMANDS] == [
        drafts.WS_TYPE_GET_LABEL_TEMPLATE_LIBRARY,
        drafts.WS_TYPE_OPEN_LABEL_TEMPLATE_DRAFT,
        drafts.WS_TYPE_AUTOSAVE_LABEL_TEMPLATE_DRAFT,
        drafts.WS_TYPE_PREVIEW_LABEL_TEMPLATE_DRAFT,
        drafts.WS_TYPE_PUBLISH_LABEL_TEMPLATE_DRAFT,
        drafts.WS_TYPE_DISCARD_LABEL_TEMPLATE_DRAFT,
    ]
    assert all(command.actor for command in drafts.COMMANDS)
    assert all(command.resolve == "any" for command in drafts.COMMANDS)
    assert all("contract" in command.schema.schema for command in drafts.COMMANDS)


@pytest.mark.parametrize(
    ("contract", "reason"),
    [
        ({}, "unknown"),
        ({"family": "some.other.product", "major": 1, "generation": 1}, "unknown"),
        (
            {
                "family": CAPABILITY_FAMILY,
                "major": 1,
                "generation": CAPABILITY_GENERATION - 1,
            },
            "stale",
        ),
    ],
)
async def test_a_stale_or_unknown_contract_is_refused_before_any_draft_is_touched(
    hass: HomeAssistant, contract: dict[str, Any], reason: str
) -> None:
    payload = await _open(hass, contract=contract)

    assert payload["outcome"] == "refused"
    assert payload["refusal"]["code"] == "label_template.contract_incompatible"
    assert payload["refusal"]["reason"] == reason
    # Nothing was created under the refused contract.
    library = await _entry_library(hass)
    state = await library.async_load()
    assert state.drafts == {}


@pytest.mark.parametrize(
    "call", [_snapshot, _open, _autosave, _preview, _publish, _discard]
)
async def test_every_command_refuses_a_stale_contract(
    hass: HomeAssistant, call: Any
) -> None:
    """One gate, on all six, so none of them is the reachable back door."""
    stale = {"family": CAPABILITY_FAMILY, "major": 1, "generation": 0}
    payload = await call(hass, contract=stale)

    assert payload["refusal"]["code"] == "label_template.contract_incompatible"


# ---------------------------------------------------------------------------
# Who is asking
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("call", [_open, _autosave, _preview, _publish, _discard])
async def test_a_non_administrator_is_refused_every_mutation_as_a_result(
    hass: HomeAssistant, call: Any
) -> None:
    """The one refusal whose recovery the card cannot perform, said plainly."""
    payload = await call(hass, user=VIEWER_USER, document={}, expected_draft_version=1)

    assert payload["outcome"] == "refused"
    assert payload["refusal"]["code"] == "label_template.not_authorized"
    assert payload["refusal"]["recovery"] == "sign_in_as_administrator"


async def test_an_unattributed_request_reads_nothing(hass: HomeAssistant) -> None:
    """A snapshot with no user attached is refused rather than served empty."""
    payload = await _snapshot(hass, user=None)

    assert payload["refusal"]["code"] == "label_template.not_authorized"


async def test_a_non_administrator_may_read_the_library_but_sees_no_drafts(
    hass: HomeAssistant,
) -> None:
    await _open(hass)

    payload = await _snapshot(hass, user=VIEWER_USER)

    assert payload["outcome"] == "ok"
    assert payload["library"]["drafts"] == []
    assert payload["library"]["store"]["readable"] is True


# ---------------------------------------------------------------------------
# Opening resumes
# ---------------------------------------------------------------------------


async def test_opening_twice_resumes_the_same_draft_rather_than_replacing_it(
    hass: HomeAssistant,
) -> None:
    """A reload, a reconnect and a second client all arrive here."""
    first = await _open(hass)
    edited = _moved(first["draft"]["document"], x_mm=7.5)
    await _autosave(hass, document=edited, expected_version=first["draft"]["version"])

    second = await _open(hass)

    assert first["resumed"] is False
    assert second["resumed"] is True
    assert second["draft"]["id"] == first["draft"]["id"]
    assert second["draft"]["document"]["elements"][0]["frame"]["x_mm"] == 7.5


async def test_resuming_ignores_a_derivation_rather_than_re_deriving_over_the_work(
    hass: HomeAssistant,
) -> None:
    """Re-deriving would be the same destruction wearing an argument."""
    opened = await _open(hass)
    await _autosave(
        hass,
        document=_moved(opened["draft"]["document"], x_mm=9.0),
        expected_version=opened["draft"]["version"],
    )

    resumed = await _open(
        hass, derive_from={"kind": FACTORY, "id": FACTORY_FOR_PROFILED_SIZE}
    )

    assert resumed["resumed"] is True
    assert resumed["draft"]["document"]["elements"][0]["frame"]["x_mm"] == 9.0


async def test_two_administrators_get_their_own_untitled_draft_of_one_stock(
    hass: HomeAssistant,
) -> None:
    mine = await _open(hass)
    theirs = await _open(hass, user=OTHER_ADMIN_USER)

    assert mine["draft"]["id"] != theirs["draft"]["id"]
    assert mine["draft"]["owner"] != theirs["draft"]["owner"]


async def test_a_draft_derived_from_a_factory_template_starts_as_its_layout(
    hass: HomeAssistant,
) -> None:
    opened = await _open(
        hass, derive_from={"kind": FACTORY, "id": FACTORY_FOR_PROFILED_SIZE}
    )

    assert opened["resumed"] is False
    assert opened["draft"]["provenance"]["factory_id"] == FACTORY_FOR_PROFILED_SIZE
    assert len(opened["draft"]["document"]["elements"]) > 1


async def test_an_unknown_label_size_is_refused_with_the_capability_to_refresh(
    hass: HomeAssistant,
) -> None:
    payload = await _open(hass, label_size_id="growspace.stock.not-a-size")

    assert payload["refusal"]["code"] == "label_template.unknown_label_size"
    assert payload["refusal"]["recovery"] == "refresh_capability"


async def test_deriving_from_a_missing_template_is_refused(
    hass: HomeAssistant,
) -> None:
    payload = await _open(
        hass,
        derive_from={"kind": "named", "id": "00000000-0000-0000-0000-000000000000"},
    )

    assert payload["refusal"]["code"] == "label_template.template_not_found"


async def test_deriving_from_another_stocks_template_cannot_change_the_size(
    hass: HomeAssistant,
) -> None:
    """A template's millimetres mean something different on different paper."""
    payload = await _open(
        hass,
        label_size_id=UNPROFILED_SIZE,
        derive_from={"kind": FACTORY, "id": FACTORY_FOR_PROFILED_SIZE},
    )

    assert payload["refusal"]["code"] == "label_template.label_size_immutable"


# ---------------------------------------------------------------------------
# Autosave keeps everything, and refuses only on version
# ---------------------------------------------------------------------------


async def test_autosave_keeps_invalid_work_and_says_why_it_cannot_publish(
    hass: HomeAssistant,
) -> None:
    """Half of editing passes through states that do not validate."""
    opened = await _open(hass)
    broken = _moved(opened["draft"]["document"], x_mm=999.0)

    payload = await _autosave(
        hass, document=broken, expected_version=opened["draft"]["version"]
    )

    assert payload["outcome"] == "ok"
    assert payload["draft"]["document"]["elements"][0]["frame"]["x_mm"] == 999.0
    assert payload["validation"]["allowed"] is False
    assert payload["validation"]["diagnostics"]


async def test_autosave_carries_the_name_an_untitled_draft_will_publish_under(
    hass: HomeAssistant,
) -> None:
    opened = await _open(hass)

    payload = await _autosave(
        hass,
        document=opened["draft"]["document"],
        name="  Bench label  ",
        expected_version=opened["draft"]["version"],
    )

    assert payload["draft"]["name"] == "Bench label"


async def test_a_second_client_cannot_write_over_newer_work_and_keeps_its_own(
    hass: HomeAssistant,
) -> None:
    """One administrator, two tabs. The older tab's payload is not thrown away."""
    opened = await _open(hass)
    base_version = opened["draft"]["version"]
    await _autosave(
        hass,
        document=_moved(opened["draft"]["document"], x_mm=4.0),
        expected_version=base_version,
    )

    refused = await _autosave(
        hass,
        document=_moved(opened["draft"]["document"], x_mm=12.0),
        expected_version=base_version,
    )

    assert refused["refusal"]["code"] == "label_template.draft_version_conflict"
    assert refused["refusal"]["recovery"] == "reload_draft"
    assert refused["refusal"]["expected_version"] == base_version
    assert refused["refusal"]["found_version"] == base_version + 1
    kept = refused["refusal"]["draft"]
    assert kept["document"]["elements"][0]["frame"]["x_mm"] == 4.0
    assert kept["recovery"]["document"]["elements"][0]["frame"]["x_mm"] == 12.0


async def test_autosaving_without_a_draft_says_to_reopen_one(
    hass: HomeAssistant,
) -> None:
    payload = await _autosave(hass, document={"schema": "growspace.label-layout"})

    assert payload["refusal"]["code"] == "label_template.draft_not_found"
    assert payload["refusal"]["recovery"] == "reopen_draft"


async def test_a_draft_whose_template_was_deleted_stops_taking_edits(
    hass: HomeAssistant,
) -> None:
    """An orphan is kept, not corrected: editing on towards a template that is
    not there would be work aimed at a revision that can never be appended."""
    from custom_components.growspace_manager.labels.library import Actor

    seed = await _open(hass)
    await _autosave(
        hass,
        document=seed["draft"]["document"],
        name="Doomed label",
        expected_version=seed["draft"]["version"],
    )
    template_id = (await _publish(hass))["template"]["id"]
    opened = await _open(hass, template_id=template_id)

    library = await _entry_library(hass)
    await library.async_delete_template(
        Actor(user_id=ADMIN, is_admin=True), template_id
    )

    payload = await _autosave(
        hass,
        template_id=template_id,
        document=opened["draft"]["document"],
        expected_version=opened["draft"]["version"],
    )

    assert payload["refusal"]["code"] == "label_template.draft_orphaned"
    assert payload["refusal"]["template_id"] == template_id


# ---------------------------------------------------------------------------
# A preview may only settle the geometry it rendered
# ---------------------------------------------------------------------------


async def test_a_preview_of_the_current_draft_returns_the_backends_own_raster(
    hass: HomeAssistant, printer: list[dict[str, Any]]
) -> None:
    opened = await _open(
        hass, derive_from={"kind": FACTORY, "id": FACTORY_FOR_PROFILED_SIZE}
    )

    payload = await _preview(hass, expected_draft_version=opened["draft"]["version"])

    assert payload["outcome"] == "ok"
    assert payload["draft_version"] == opened["draft"]["version"]
    assert payload["render"]["raster"]["image"].startswith("data:image/png;base64,")
    assert payload["render"]["render_context"]["operation"] == "preview"


async def test_a_preview_of_a_version_the_draft_has_passed_is_refused(
    hass: HomeAssistant, printer: list[dict[str, Any]]
) -> None:
    """The alternative is a raster of an older layout with nothing saying so."""
    opened = await _open(
        hass, derive_from={"kind": FACTORY, "id": FACTORY_FOR_PROFILED_SIZE}
    )
    await _autosave(
        hass,
        document=_moved(opened["draft"]["document"], x_mm=3.0),
        expected_version=opened["draft"]["version"],
    )

    payload = await _preview(hass, expected_draft_version=opened["draft"]["version"])

    assert payload["refusal"]["code"] == "label_template.draft_version_mismatch"
    assert payload["refusal"]["found_version"] == opened["draft"]["version"] + 1
    assert printer == []


async def test_an_invalid_draft_previews_as_its_diagnostics_not_as_a_picture(
    hass: HomeAssistant, printer: list[dict[str, Any]]
) -> None:
    opened = await _open(hass)
    saved = await _autosave(
        hass,
        document=_moved(opened["draft"]["document"], x_mm=999.0),
        expected_version=opened["draft"]["version"],
    )

    payload = await _preview(hass, expected_draft_version=saved["draft"]["version"])

    assert payload["refusal"]["code"] == "label_template.draft_not_publishable"
    assert payload["refusal"]["recovery"] == "fix_layout"
    assert payload["refusal"]["diagnostics"]
    assert printer == []


async def test_a_stock_no_printer_can_render_is_refused_without_a_round_trip(
    hass: HomeAssistant, printer: list[dict[str, Any]]
) -> None:
    await _open(hass, label_size_id=UNPROFILED_SIZE)

    payload = await _preview(
        hass, label_size_id=UNPROFILED_SIZE, expected_draft_version=1
    )

    assert payload["refusal"]["code"] == "label_template.no_capability_profile"
    assert payload["refusal"]["recovery"] == "choose_another_label_size"
    assert printer == []


async def test_previewing_without_a_draft_says_to_reopen_one(
    hass: HomeAssistant, printer: list[dict[str, Any]]
) -> None:
    payload = await _preview(hass, expected_draft_version=1)

    assert payload["refusal"]["code"] == "label_template.draft_not_found"


async def test_an_unsupported_locale_and_an_unknown_fixture_are_named(
    hass: HomeAssistant,
) -> None:
    by_locale = await _preview(hass, expected_draft_version=1, locale="xx")
    by_fixture = await _preview(
        hass, expected_draft_version=1, fixture_family="not-a-family"
    )

    assert by_locale["refusal"]["code"] == "label_template.unsupported_locale"
    assert by_fixture["refusal"]["code"] == "label_template.unknown_fixture"


# ---------------------------------------------------------------------------
# Publishing, and the three refusals that cost nothing
# ---------------------------------------------------------------------------


async def test_a_valid_named_draft_publishes_as_a_named_template(
    hass: HomeAssistant,
) -> None:
    opened = await _open(hass)
    await _autosave(
        hass,
        document=opened["draft"]["document"],
        name="Bench label",
        expected_version=opened["draft"]["version"],
    )

    payload = await _publish(hass)

    assert payload["outcome"] == "ok"
    assert payload["template"]["name"] == "Bench label"
    assert payload["revision"]["revision"] == 1

    after = await _snapshot(hass)
    assert [item["name"] for item in after["library"]["templates"]] == ["Bench label"]
    assert after["library"]["drafts"] == []


async def test_publish_cannot_consume_a_newer_autosave(
    hass: HomeAssistant,
) -> None:
    opened = await _open(hass)
    saved = await _autosave(
        hass,
        document=opened["draft"]["document"],
        name="Bench label",
        expected_version=opened["draft"]["version"],
    )
    latest = await _autosave(
        hass,
        document=_moved(saved["draft"]["document"], x_mm=1.5),
        expected_version=saved["draft"]["version"],
    )

    payload = await _publish(hass, expected_draft_version=saved["draft"]["version"])

    assert payload["refusal"]["code"] == "label_template.draft_version_conflict"
    assert payload["refusal"]["expected_version"] == saved["draft"]["version"]
    assert payload["refusal"]["found_version"] == latest["draft"]["version"]
    assert payload["refusal"]["draft"]["version"] == latest["draft"]["version"]


async def test_publishing_an_unnamed_draft_is_refused_and_keeps_it(
    hass: HomeAssistant,
) -> None:
    opened = await _open(hass)

    payload = await _publish(hass)

    assert payload["refusal"]["code"] == "label_template.name_required"
    assert payload["refusal"]["recovery"] == "rename"
    resumed = await _open(hass)
    assert resumed["draft"]["id"] == opened["draft"]["id"]


async def test_publishing_an_invalid_draft_is_refused_with_its_diagnostics(
    hass: HomeAssistant,
) -> None:
    opened = await _open(hass)
    await _autosave(
        hass,
        document=_moved(opened["draft"]["document"], x_mm=999.0),
        name="Off the paper",
        expected_version=opened["draft"]["version"],
    )

    payload = await _publish(hass)

    assert payload["refusal"]["code"] == "label_template.draft_not_publishable"
    assert payload["refusal"]["diagnostics"]


async def test_a_name_another_template_of_this_stock_holds_is_refused(
    hass: HomeAssistant,
) -> None:
    first = await _open(hass)
    await _autosave(
        hass,
        document=first["draft"]["document"],
        name="Bench label",
        expected_version=first["draft"]["version"],
    )
    await _publish(hass)

    second = await _open(hass)
    await _autosave(
        hass,
        document=second["draft"]["document"],
        name="bench label",
        expected_version=second["draft"]["version"],
    )
    payload = await _publish(hass)

    assert payload["refusal"]["code"] == "label_template.duplicate_name"
    assert payload["refusal"]["recovery"] == "rename"


async def test_publishing_without_a_draft_says_to_reopen_one(
    hass: HomeAssistant,
) -> None:
    payload = await _publish(hass)

    assert payload["refusal"]["code"] == "label_template.draft_not_found"


async def test_a_draft_overtaken_by_another_administrator_cannot_publish_over_them(
    hass: HomeAssistant,
) -> None:
    """The stale refusal, which leaves the overtaken work exactly where it was.

    The other half of "edit and save end to end": a published Label Template
    is edited again, through the same commands, and the second editor is
    refused rather than allowed to drop the first one's revision.
    """
    seed = await _open(hass)
    await _autosave(
        hass,
        document=seed["draft"]["document"],
        name="Shared label",
        expected_version=seed["draft"]["version"],
    )
    template_id = (await _publish(hass))["template"]["id"]

    mine = await _open(hass, template_id=template_id)
    theirs = await _open(hass, user=OTHER_ADMIN_USER, template_id=template_id)
    assert mine["draft"]["base_revision"] == theirs["draft"]["base_revision"] == 1

    # They publish first, from the same base.
    await _autosave(
        hass,
        user=OTHER_ADMIN_USER,
        template_id=template_id,
        document=_moved(theirs["draft"]["document"], x_mm=3.0),
        expected_version=theirs["draft"]["version"],
    )
    assert (await _publish(hass, user=OTHER_ADMIN_USER, template_id=template_id))[
        "outcome"
    ] == "ok"

    await _autosave(
        hass,
        template_id=template_id,
        document=_moved(mine["draft"]["document"], x_mm=1.5),
        expected_version=mine["draft"]["version"],
    )
    payload = await _publish(hass, template_id=template_id)

    assert payload["refusal"]["code"] == "label_template.draft_stale"
    assert payload["refusal"]["recovery"] == "reload_draft"
    assert payload["refusal"]["base_revision"] == 1
    assert payload["refusal"]["head_revision"] == 2

    # Stale is not lost: the work is still there, and still says it is stale.
    kept = await _open(hass, template_id=template_id)
    assert kept["draft"]["document"]["elements"][0]["frame"]["x_mm"] == 1.5
    stale = next(
        item
        for item in (await _snapshot(hass))["library"]["drafts"]
        if item["template_id"] == template_id
    )
    assert stale["stale"] is True


async def test_a_name_on_a_template_bound_draft_is_refused_rather_than_guessed(
    hass: HomeAssistant,
) -> None:
    """Renaming a published Label Template is its own operation, on the template."""
    seed = await _open(hass)
    await _autosave(
        hass,
        document=seed["draft"]["document"],
        name="Shared label",
        expected_version=seed["draft"]["version"],
    )
    template_id = (await _publish(hass))["template"]["id"]
    opened = await _open(hass, template_id=template_id)

    payload = await _autosave(
        hass,
        template_id=template_id,
        document=opened["draft"]["document"],
        name="Something else",
        expected_version=opened["draft"]["version"],
    )

    assert payload["refusal"]["code"] == "label_template.name_not_on_template_draft"


# ---------------------------------------------------------------------------
# Discarding, explicitly
# ---------------------------------------------------------------------------


async def test_discarding_returns_the_work_it_removed(hass: HomeAssistant) -> None:
    opened = await _open(hass)

    payload = await _discard(hass)

    assert payload["outcome"] == "ok"
    assert payload["draft"]["id"] == opened["draft"]["id"]
    after = await _snapshot(hass)
    assert after["library"]["drafts"] == []


async def test_discarding_nothing_says_so(hass: HomeAssistant) -> None:
    payload = await _discard(hass)

    assert payload["refusal"]["code"] == "label_template.draft_not_found"


# ---------------------------------------------------------------------------
# The shape the card is held to
# ---------------------------------------------------------------------------

FIXTURES = Path(__file__).parent.parent / "fixtures" / "contract"

#: A Crockford ULID (drafts, element IDs) or a UUID (Named Templates).
_OPAQUE = re.compile(
    r"^(?:[0-9A-HJKMNP-TV-Z]{26}"
    r"|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$"
)


def _stable(value: Any, seen: dict[str, str] | None = None) -> Any:
    """Replace minted identities with stable placeholders, in first-seen order.

    The recorded payloads are the *shape* the card parses, and a draft ID, a
    template UUID and an element ID are freshly minted on every run: a fixture
    that re-recorded them would assert that a random string is a random string
    and would change on every regeneration. Everything else -- the field names,
    the nesting, the versions, the validation rows -- is exact, which is what
    the card is actually held to.
    """
    seen = {} if seen is None else seen
    if isinstance(value, dict):
        return {key: _stable(item, seen) for key, item in value.items()}
    if isinstance(value, list):
        return [_stable(item, seen) for item in value]
    if isinstance(value, str) and _OPAQUE.match(value):
        return seen.setdefault(value, f"<opaque-{len(seen) + 1}>")
    return value


def _record(name: str, payload: Any, pytestconfig: pytest.Config) -> None:
    """Compare one payload with its recorded shape, regenerating on request."""
    path = FIXTURES / f"{name}.json"
    stable = _stable(payload)
    if pytestconfig.getoption("regenerate_contract_fixture"):
        path.write_text(
            f"{json.dumps(stable, indent=2, sort_keys=True)}\n", encoding="utf-8"
        )
    assert path.exists()
    assert stable == json.loads(path.read_text(encoding="utf-8"))


@freeze_time("2026-09-18T00:00:00+00:00")
async def test_the_shared_editing_fixtures_are_exact(
    hass: HomeAssistant,
    printer: list[dict[str, Any]],
    pytestconfig: pytest.Config,
) -> None:
    """One recorded response per payload the card's schema is parsed against.

    Recorded in one test because they are one session: the library snapshot
    before anything exists, the draft that opening it produced, the autosave
    that kept an edit, the raster that settled it, the conflict a second
    client would have caused, and the revision it published.
    """
    hass.config.time_zone = "UTC"

    opened = await _open(
        hass, derive_from={"kind": FACTORY, "id": FACTORY_FOR_PROFILED_SIZE}
    )
    _record("label_draft_opened_v1", opened, pytestconfig)

    saved = await _autosave(
        hass,
        document=_moved(opened["draft"]["document"], x_mm=2.5),
        name="Bench label",
        expected_version=opened["draft"]["version"],
    )
    _record("label_draft_saved_v1", saved, pytestconfig)

    conflict = await _autosave(
        hass,
        document=_moved(opened["draft"]["document"], x_mm=6.0),
        expected_version=opened["draft"]["version"],
    )
    _record("label_draft_conflict_v1", conflict, pytestconfig)

    current = await _open(hass)
    preview = await _preview(hass, expected_draft_version=current["draft"]["version"])
    _record("label_draft_preview_v1", preview, pytestconfig)

    _record("label_template_library_v1", await _snapshot(hass), pytestconfig)
    _record("label_draft_published_v1", await _publish(hass), pytestconfig)
