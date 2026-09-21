"""Administrator lifecycle commands, preserving the library's transactional rules."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.exceptions import EntityNotFoundError
from custom_components.growspace_manager.labels.library import TemplateRef
from custom_components.growspace_manager.labels.library.errors import LabelTemplateError
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import Unauthorized

from ._common import WSCommand
from .drafts import _actor, _base_schema, _gate, _library, _ok, _refused, _unauthorized

WS_TYPE = "growspace_manager/manage_label_templates"
_REFERENCE = {
    vol.Required("kind"): vol.In(["factory", "named"]),
    vol.Required("id"): str,
}
_SLOT = {vol.Optional("template_id"): str, vol.Optional("label_size_id"): str}
_IMPORT = {
    vol.Required("bundle"): object,
    vol.Optional("as_copy", default=[]): [str],
    vol.Optional("names", default={}): {str: str},
}
_PAYLOADS: dict[str, dict[Any, Any]] = {
    "snapshot": {},
    "inspect": {vol.Required("template_id"): str},
    "export": {vol.Optional("refs"): [vol.Schema(_REFERENCE)]},
    "preflight": _IMPORT,
    "import": _IMPORT,
    "rename": {vol.Required("template_id"): str, vol.Required("name"): str},
    "duplicate": {vol.Required("ref"): _REFERENCE, vol.Required("name"): str},
    "save_as": {**_SLOT, vol.Required("name"): str, vol.Required("draft_id"): str},
    "replace_factory": {
        vol.Required("template_id"): str,
        vol.Optional("factory_id"): str,
    },
    "restore_revision": {
        vol.Required("template_id"): str,
        vol.Required("revision"): int,
    },
    "set_default": {
        vol.Required("label_size_id"): str,
        vol.Required("ref"): _REFERENCE,
    },
    "clear_default": {vol.Required("label_size_id"): str},
    "delete": {vol.Required("template_id"): str},
    "restore": {vol.Required("template_id"): str, vol.Optional("name"): str},
    "reload": {vol.Required("template_id"): str},
    "discard": _SLOT,
}
_PAYLOADS["save_as"][vol.Optional("recovery_document")] = object
for _draft_operation in ("save_as", "replace_factory", "reload", "discard"):
    _PAYLOADS[_draft_operation][vol.Optional("expected_draft_version")] = int
_METHODS = {
    "rename": "async_rename_template",
    "duplicate": "async_duplicate_template",
    "save_as": "async_save_as",
    "replace_factory": "async_replace_from_factory",
    "restore_revision": "async_restore_revision",
    "set_default": "async_set_default",
    "clear_default": "async_clear_default",
    "delete": "async_delete_template",
    "restore": "async_restore_template",
    "reload": "async_reload_draft",
    "discard": "async_discard_draft",
    "import": "async_import_templates",
}
SCHEMA = _base_schema(WS_TYPE).extend(
    {
        vol.Required("operation"): vol.In(_PAYLOADS),
        vol.Required("payload"): dict,
        vol.Optional("expected_generation"): int,
        vol.Optional("idempotency_key"): str,
    }
)


async def websocket_manage_label_templates(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> dict[str, Any]:
    """Authorize afresh, validate the selected verb and delegate to the library."""
    if (refusal := _gate(msg)) is not None:
        return refusal
    actor = _actor(msg)
    try:
        actor.administrator()
        operation = msg["operation"]
        payload = vol.Schema(_PAYLOADS[operation])(msg["payload"])
        library = await _library(hass, coordinator)
        if operation == "snapshot":
            return _ok(library=await library.async_snapshot(actor), result=None)
        if operation == "inspect":
            result = await library.async_inspect_template(actor, **payload)
        elif operation == "export":
            refs = payload.get("refs")
            result = await library.async_export_templates(
                actor,
                None if refs is None else [TemplateRef.from_dict(ref) for ref in refs],
            )
        elif operation == "preflight":
            result = await library.async_preflight_import(actor, **payload)
        else:
            # No mutation without the generation the administrator reviewed.
            # The library checks it under its lock, after idempotent replay.
            if "expected_generation" not in msg or not msg.get("idempotency_key"):
                return _refused(
                    "label_template.version_required",
                    "Refresh the library before changing it.",
                    "refresh_library",
                )
            if "ref" in payload:
                payload["ref"] = TemplateRef.from_dict(payload["ref"])
            method = getattr(library, _METHODS[operation])
            result = (
                await method(
                    actor,
                    **payload,
                    expected_generation=msg["expected_generation"],
                    idempotency_key=msg["idempotency_key"],
                )
            ).as_dict()
        return _ok(library=await library.async_snapshot(actor), result=result)
    except Unauthorized as error:
        return _unauthorized(error)
    except vol.Invalid as error:
        return _refused("label_template.invalid_operation", str(error), "none")
    except (LabelTemplateError, EntityNotFoundError) as error:
        # These are domain refusals, never transport failures. Complete opaque
        # documents remain in the store; a failed operation cannot trim them.
        return _refused(
            f"label_template.{type(error).__name__}", str(error), "refresh_library"
        )


COMMANDS = [
    WSCommand(
        WS_TYPE, websocket_manage_label_templates, SCHEMA, resolve="any", actor=True
    )
]
