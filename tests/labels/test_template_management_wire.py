"""Lifecycle wire: identities, atomic import, authorization and stale review."""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import pytest

from custom_components.growspace_manager.labels.canonical import LABEL_SIZES, digest
from custom_components.growspace_manager.labels.capability import contract_identity
from custom_components.growspace_manager.labels.library import Actor, async_get_library
from custom_components.growspace_manager.websocket._common import WS_MSG_USER
from custom_components.growspace_manager.websocket.template_management import (
    websocket_manage_label_templates,
)

SIZE = next(iter(LABEL_SIZES))
ADMIN = Actor(user_id="admin", is_admin=True)
COORDINATOR = SimpleNamespace(config_entry=SimpleNamespace(entry_id="lifecycle"))


async def call(hass, operation, payload=None, *, generation=None, key=None, admin=True):
    message: dict[str, Any] = {
        "contract": contract_identity(),
        "operation": operation,
        "payload": payload or {},
        WS_MSG_USER: SimpleNamespace(id="admin", is_admin=admin),
    }
    if generation is not None:
        message["expected_generation"] = generation
    if key is not None:
        message["idempotency_key"] = key
    return await websocket_manage_label_templates(hass, COORDINATOR, message)


async def named(hass, *, factory=False):
    library = await async_get_library(hass, "lifecycle")
    from custom_components.growspace_manager.labels.canonical import (
        factory_template_for_size,
    )
    from custom_components.growspace_manager.labels.library import TemplateRef

    draft = await library.async_create_draft(
        ADMIN,
        label_size_id=SIZE,
        derive_from=TemplateRef(kind="factory", id=factory_template_for_size(SIZE).id)
        if factory
        else None,
    )
    await library.async_autosave_draft(
        ADMIN,
        label_size_id=SIZE,
        document=draft.document,
        name="Original",
        expected_version=draft.version,
    )
    publication = await library.async_publish_draft(ADMIN, label_size_id=SIZE)
    return library, publication.template.id


async def test_lifecycle_preserves_history_identity_and_default(hass):
    library, identity = await named(hass)

    async def mutate(operation, payload):
        result = await call(
            hass, operation, payload, generation=library.state.generation, key=operation
        )
        assert result["outcome"] == "ok", result
        return result

    renamed = await mutate("rename", {"template_id": identity, "name": "Renamed"})
    assert renamed["result"]["template"]["id"] == identity
    await mutate(
        "set_default", {"label_size_id": SIZE, "ref": {"kind": "named", "id": identity}}
    )
    await library.async_open_draft(ADMIN, identity)
    deleted = await mutate("delete", {"template_id": identity})
    assert deleted["library"]["drafts"][0]["orphaned"]
    assert deleted["library"]["effective_defaults"][SIZE]["ref"]["kind"] == "factory"
    inspected = await call(hass, "inspect", {"template_id": identity})
    assert len(inspected["result"]["revisions"]) == 2
    await mutate("restore", {"template_id": identity})
    assert SIZE not in library.state.defaults
    restored = await mutate(
        "restore_revision", {"template_id": identity, "revision": 1}
    )
    assert restored["result"]["revision"]["revision"] == 3
    duplicate = await mutate(
        "duplicate", {"ref": {"kind": "named", "id": identity}, "name": "Copy"}
    )
    assert duplicate["result"]["template"]["id"] != identity
    await mutate("clear_default", {"label_size_id": SIZE})
    await mutate("replace_factory", {"template_id": identity})
    await mutate("reload", {"template_id": identity})
    saved = await mutate(
        "save_as",
        {
            "template_id": identity,
            "draft_id": next(iter(library.state.drafts.values())).id,
            "name": "Saved As",
        },
    )
    assert saved["result"]["template"]["id"] != identity
    await library.async_open_draft(ADMIN, identity)
    await mutate("discard", {"template_id": identity})
    assert not library.state.drafts


@pytest.mark.parametrize(
    "operation,payload",
    [
        ("rename", {"template_id": "id", "name": "New"}),
        ("duplicate", {"ref": {"kind": "named", "id": "id"}, "name": "Copy"}),
        ("save_as", {"label_size_id": SIZE, "name": "New", "draft_id": "draft"}),
        ("replace_factory", {"template_id": "id"}),
        ("restore_revision", {"template_id": "id", "revision": 1}),
        ("set_default", {"label_size_id": SIZE, "ref": {"kind": "named", "id": "id"}}),
        ("clear_default", {"label_size_id": SIZE}),
        ("delete", {"template_id": "id"}),
        ("restore", {"template_id": "id"}),
        ("reload", {"template_id": "id"}),
        ("discard", {"label_size_id": SIZE}),
        ("import", {"bundle": {}}),
    ],
)
async def test_all_mutations_require_current_review_and_authority(
    hass, operation, payload
):
    library, _ = await named(hass)
    before = library.state.as_dict()
    denied = await call(
        hass, operation, payload, generation=1, key="denied", admin=False
    )
    assert denied["refusal"]["code"] == "label_template.not_authorized"
    missing = await call(hass, operation, payload)
    assert missing["refusal"]["code"] == "label_template.version_required"
    stale = await call(hass, operation, payload, generation=0, key="stale")
    assert stale["refusal"]["code"] == "label_template.LibraryVersionConflict"
    assert library.state.as_dict() == before


async def test_preflight_lists_identity_and_name_conflicts_without_writes(hass):
    library, identity = await named(hass)
    exported = await call(hass, "export")
    bundle = deepcopy(exported["result"])
    entry = bundle["templates"][0]
    entry["document"]["elements"][0]["frame"]["x_mm"] += 1
    from custom_components.growspace_manager.labels.library.publication import (
        check_document,
    )

    entry["digest"] = check_document(entry["document"]).layout.digest
    bundle["checksum"] = digest({k: v for k, v in bundle.items() if k != "checksum"})
    before = library.state.as_dict()
    preflight = await call(hass, "preflight", {"bundle": bundle})
    assert any(
        issue["code"] == "ImportCollision" for issue in preflight["result"]["issues"]
    )
    preflight = await call(hass, "preflight", {"bundle": bundle, "as_copy": [identity]})
    assert any(
        issue["code"] == "DuplicateTemplateName"
        for issue in preflight["result"]["issues"]
    )
    assert library.state.as_dict() == before
    empty_name = await call(
        hass,
        "preflight",
        {"bundle": bundle, "as_copy": [identity], "names": {identity: "  "}},
    )
    assert any(
        issue["code"] == "TemplateNameRequired"
        for issue in empty_name["result"]["issues"]
    )
    payload = {"bundle": bundle, "as_copy": [identity], "names": {identity: "Imported"}}
    preflight = await call(hass, "preflight", payload)
    assert preflight["result"]["ready"]
    imported = await call(hass, "import", payload, generation=1, key="import")
    assert imported["outcome"] == "ok"
    replay = await call(hass, "import", payload, generation=1, key="import")
    assert replay["result"]["replayed"]
    assert len(library.state.templates) == 2


async def test_read_refusals_and_invalid_requests(hass):
    assert (await call(hass, "inspect", {"template_id": "missing"}))[
        "outcome"
    ] == "refused"
    assert (await call(hass, "rename", {}))["refusal"][
        "code"
    ] == "label_template.invalid_operation"
    assert (await call(hass, "snapshot"))["outcome"] == "ok"
    result = await websocket_manage_label_templates(hass, COORDINATOR, {"contract": {}})
    assert result["outcome"] == "refused"


async def test_save_as_of_rejected_local_work_preserves_the_server_draft(hass):
    library, identity = await named(hass)
    draft = await library.async_open_draft(ADMIN, identity)
    local = deepcopy(draft.document)
    local["elements"][0]["frame"]["x_mm"] += 1
    result = await call(
        hass,
        "save_as",
        {
            "template_id": identity,
            "draft_id": draft.id,
            "name": "Recovered",
            "recovery_document": local,
        },
        generation=1,
        key="recover",
    )
    assert result["outcome"] == "ok"
    assert library.state.drafts[draft.key].document == draft.document
    assert result["result"]["template"]["id"] != identity


@pytest.mark.parametrize(
    "operation", ["save_as", "replace_factory", "reload", "discard"]
)
async def test_management_cannot_consume_a_newer_autosave(hass, operation):
    library, identity = await named(hass)
    draft = await library.async_open_draft(ADMIN, identity)
    payload = {"template_id": identity, "expected_draft_version": draft.version}
    if operation == "save_as":
        payload.update(name="Copy", draft_id=draft.id)
    await library.async_autosave_draft(
        ADMIN,
        template_id=identity,
        document=draft.document,
        expected_version=draft.version,
    )
    result = await call(hass, operation, payload, generation=1, key="stale-draft")
    assert result["refusal"]["code"] == "label_template.DraftVersionConflict"
    assert library.state.drafts[draft.key].version == 2


async def test_management_contract_fixtures(hass, pytestconfig):
    from freezegun import freeze_time

    from .test_draft_editing_wire import _record

    with freeze_time("2026-09-21T00:00:00+00:00"):
        library, identity = await named(hass, factory=True)
        await library.async_open_draft(ADMIN, identity)
        _record(
            "label_management_snapshot_v1", await call(hass, "snapshot"), pytestconfig
        )
        _record(
            "label_management_inspection_v1",
            await call(hass, "inspect", {"template_id": identity}),
            pytestconfig,
        )
        exported = await call(hass, "export")
        _record(
            "label_management_preflight_v1",
            await call(hass, "preflight", {"bundle": exported["result"]}),
            pytestconfig,
        )
        await call(
            hass, "delete", {"template_id": identity}, generation=1, key="delete"
        )
        _record(
            "label_management_deleted_v1", await call(hass, "snapshot"), pytestconfig
        )
