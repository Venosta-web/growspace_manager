"""The Template Draft editing seam: open, autosave, preview, publish, discard.

The library beside this module has held the whole draft lifecycle since the
template work landed. What was missing was the wire, and the shape of that
wire is where every decision in this file is.

**Every refusal is a result.** Not a transport error -- the same rule the
Factory Template preview follows, for the same reason. An editor has to tell
"somebody else saved over you" from "this layout does not validate yet" from
"you are no longer an administrator" and do something different about each,
and Home Assistant's error frame carries one code from a fixed vocabulary that
the card flattens to `internal_error` when it does not recognise it. So each
refusal is one structured row naming its own code, the recovery that applies,
and whatever the client needs to act -- the stored draft, the diagnostics, the
two versions that disagreed.

**The authority is recomputed here, per command.** Every handler takes the
acting user off the message and hands the library an `Actor` built from it,
because the library re-derives authority on every call on purpose: an
administrator demoted with the editor open keeps their draft and loses every
mutation. That is only true if the user travels with the request rather than
being captured when the editor opened.

**A preview may only settle the geometry it rendered.** `preview_draft` takes
the draft version the editor believes it is looking at and refuses when the
stored draft has moved past it. Without that the editor would be left
comparing timestamps to decide whether the picture on screen is of the layout
under it, and the one thing a raster preview must never do is look settled
over geometry it does not show.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.labels.canonical import (
    SUPPORTED_LOCALES,
    TYPICAL,
    PrintContext,
    profiles_for_size,
    representative_subject,
)
from custom_components.growspace_manager.labels.capability import (
    IncompatibleLabelTemplateContract,
    contract_identity,
    require_contract,
)
from custom_components.growspace_manager.labels.library import (
    Actor,
    DraftIsOrphaned,
    DraftIsStale,
    DraftNotFound,
    DraftNotPublishable,
    DraftVersionConflict,
    DuplicateTemplateName,
    LabelSizeImmutable,
    LabelTemplateLibrary,
    TemplateNameRequired,
    TemplateNotFound,
    TemplateRef,
    UnsupportedLabelSize,
    async_get_library,
)
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import Unauthorized

from ._common import WS_MSG_USER, WSCommand

WS_TYPE_GET_LABEL_TEMPLATE_LIBRARY = f"{DOMAIN}/get_label_template_library"
WS_TYPE_OPEN_LABEL_TEMPLATE_DRAFT = f"{DOMAIN}/open_label_template_draft"
WS_TYPE_AUTOSAVE_LABEL_TEMPLATE_DRAFT = f"{DOMAIN}/autosave_label_template_draft"
WS_TYPE_PREVIEW_LABEL_TEMPLATE_DRAFT = f"{DOMAIN}/preview_label_template_draft"
WS_TYPE_PUBLISH_LABEL_TEMPLATE_DRAFT = f"{DOMAIN}/publish_label_template_draft"
WS_TYPE_DISCARD_LABEL_TEMPLATE_DRAFT = f"{DOMAIN}/discard_label_template_draft"

OK = "ok"
REFUSED = "refused"

#: What a client can *do* about a refusal. Deliberately a growing vocabulary
#: rather than a closed one: a card that does not recognise a verb shows the
#: reason and offers nothing automatic, which is always a safe answer.
RECOVERY_REFRESH_CAPABILITY = "refresh_capability"
RECOVERY_RELOAD_DRAFT = "reload_draft"
RECOVERY_RENAME = "rename"
RECOVERY_FIX_LAYOUT = "fix_layout"
RECOVERY_REOPEN_DRAFT = "reopen_draft"
RECOVERY_SIGN_IN_AS_ADMIN = "sign_in_as_administrator"
RECOVERY_CHOOSE_ANOTHER_SIZE = "choose_another_label_size"
RECOVERY_NONE = "none"

CODE_NOT_AUTHORIZED = "label_template.not_authorized"
CODE_DRAFT_NOT_FOUND = "label_template.draft_not_found"
CODE_DRAFT_VERSION_CONFLICT = "label_template.draft_version_conflict"
CODE_DRAFT_VERSION_MISMATCH = "label_template.draft_version_mismatch"
CODE_DRAFT_STALE = "label_template.draft_stale"
CODE_DRAFT_ORPHANED = "label_template.draft_orphaned"
CODE_DRAFT_NOT_PUBLISHABLE = "label_template.draft_not_publishable"
CODE_NAME_REQUIRED = "label_template.name_required"
CODE_DUPLICATE_NAME = "label_template.duplicate_name"
CODE_UNKNOWN_LABEL_SIZE = "label_template.unknown_label_size"
CODE_LABEL_SIZE_IMMUTABLE = "label_template.label_size_immutable"
CODE_TEMPLATE_NOT_FOUND = "label_template.template_not_found"
CODE_NO_CAPABILITY_PROFILE = "label_template.no_capability_profile"
CODE_UNKNOWN_FIXTURE = "label_template.unknown_fixture"
CODE_UNSUPPORTED_LOCALE = "label_template.unsupported_locale"
CODE_NAME_NOT_ON_DRAFT = "label_template.name_not_on_template_draft"


def _base_schema(command: str) -> vol.Schema:
    """Return the schema every draft command shares.

    `contract` is typed no further than "a mapping" on purpose. A stale or
    foreign identity is exactly what these commands exist to refuse legibly,
    and a schema rejection would turn that into a validation error with
    nothing in it for the card to act on.
    """
    return websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
        {
            vol.Required("type"): command,
            vol.Required("contract"): dict,
        }
    )


SCHEMA_WS_GET_LABEL_TEMPLATE_LIBRARY = _base_schema(WS_TYPE_GET_LABEL_TEMPLATE_LIBRARY)

#: Which draft a command addresses. A Label Template's own draft when
#: `template_id` names one, and this administrator's untitled draft for the
#: stock otherwise -- the two slots the store keeps, named the way it keeps
#: them rather than collapsed into one ambiguous identifier.
_SLOT = {
    vol.Required("label_size_id"): str,
    vol.Optional("template_id"): vol.Any(None, str),
}

SCHEMA_WS_OPEN_LABEL_TEMPLATE_DRAFT = _base_schema(
    WS_TYPE_OPEN_LABEL_TEMPLATE_DRAFT
).extend(
    {
        **_SLOT,
        vol.Optional("derive_from"): vol.Any(
            None, vol.Schema({vol.Required("kind"): str, vol.Required("id"): str})
        ),
    }
)

SCHEMA_WS_AUTOSAVE_LABEL_TEMPLATE_DRAFT = _base_schema(
    WS_TYPE_AUTOSAVE_LABEL_TEMPLATE_DRAFT
).extend(
    {
        **_SLOT,
        # Untyped because the document layer is the authority on documents.
        # A schema rejection here would refuse an invalid draft, and keeping
        # invalid work is half of what autosave is for.
        vol.Required("document"): object,
        vol.Optional("name"): vol.Any(None, str),
        vol.Optional("expected_version"): vol.Any(None, int),
    }
)

SCHEMA_WS_PREVIEW_LABEL_TEMPLATE_DRAFT = _base_schema(
    WS_TYPE_PREVIEW_LABEL_TEMPLATE_DRAFT
).extend(
    {
        **_SLOT,
        vol.Required("expected_draft_version"): int,
        vol.Optional("context", default=str(PrintContext.STRAIN)): str,
        vol.Optional("fixture_family", default=TYPICAL): str,
        vol.Optional("density", default="normal"): str,
        vol.Optional("locale", default=SUPPORTED_LOCALES[0]): str,
    }
)

SCHEMA_WS_PUBLISH_LABEL_TEMPLATE_DRAFT = _base_schema(
    WS_TYPE_PUBLISH_LABEL_TEMPLATE_DRAFT
).extend(
    {
        **_SLOT,
        vol.Optional("draft_id"): vol.Any(None, str),
        vol.Optional("idempotency_key"): vol.Any(None, str),
    }
)

SCHEMA_WS_DISCARD_LABEL_TEMPLATE_DRAFT = _base_schema(
    WS_TYPE_DISCARD_LABEL_TEMPLATE_DRAFT
).extend(dict(_SLOT))


# ---------------------------------------------------------------------------
# Shaping one answer
# ---------------------------------------------------------------------------


def _refused(code: str, reason: str, recovery: str, **extra: Any) -> dict[str, Any]:
    """Shape one refusal the same way whatever refused."""
    return {
        "outcome": REFUSED,
        "refusal": {
            "code": code,
            "reason": reason,
            "recovery": recovery,
            "current": contract_identity(),
            **extra,
        },
    }


def _ok(**payload: Any) -> dict[str, Any]:
    """Shape one success, carrying the contract it was served under."""
    return {"outcome": OK, "contract": contract_identity(), **payload}


def _slot(msg: dict[str, Any]) -> dict[str, Any]:
    """Return the one slot key the library addresses a draft by.

    The store keeps two kinds of slot and a draft is addressed by exactly one
    of them, so the message carrying both -- `label_size_id` is always present,
    because the preview needs it to find a Capability Profile even for a
    template-bound draft -- is narrowed here rather than in five handlers.
    """
    template_id = msg.get("template_id")
    if template_id is not None:
        return {"template_id": template_id, "label_size_id": None}
    return {"template_id": None, "label_size_id": msg["label_size_id"]}


def _actor(msg: dict[str, Any]) -> Actor:
    """Build the acting identity from the user the lifecycle put on the message."""
    return Actor.from_user(msg.get(WS_MSG_USER))


async def _library(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator
) -> LabelTemplateLibrary:
    """Return this config entry's library."""
    return await async_get_library(hass, coordinator.config_entry.entry_id)


def _gate(msg: dict[str, Any]) -> dict[str, Any] | None:
    """Refuse a command whose contract identity is not the current one."""
    try:
        require_contract(msg["contract"])
    except IncompatibleLabelTemplateContract as refused:
        return {"outcome": REFUSED, "refusal": refused.as_dict()}
    return None


def _unauthorized(error: Unauthorized) -> dict[str, Any]:
    """Shape the one refusal that is about who is asking, not about the work.

    Named separately from the others because its recovery is the only one the
    card cannot perform: nothing in an editor turns its user into an
    administrator. Saying so is the whole of the answer.
    """
    return _refused(
        CODE_NOT_AUTHORIZED,
        "Managing Label Templates requires a Home Assistant administrator.",
        RECOVERY_SIGN_IN_AS_ADMIN,
        permission=getattr(error, "permission", None),
    )


def _conflict(error: DraftVersionConflict) -> dict[str, Any]:
    """Shape a refused autosave, with the work it did not throw away.

    The draft comes back whole because the rejected payload is *on* it, in the
    recovery slot the library parked it in. A client told only that it lost
    the race would have to decide whether its unsaved work still exists; this
    one can see it.
    """
    draft = error.draft
    return _refused(
        CODE_DRAFT_VERSION_CONFLICT,
        str(error),
        RECOVERY_RELOAD_DRAFT,
        expected_version=error.expected,
        found_version=error.found,
        draft=draft.as_dict() if hasattr(draft, "as_dict") else None,
    )


# ---------------------------------------------------------------------------
# The library, whole
# ---------------------------------------------------------------------------


async def websocket_get_label_template_library(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> dict[str, Any]:
    """Return the authoritative snapshot this actor may see.

    The refresh a client falls back to after a reload, a reconnect, or a
    generation gap, and the only place an editor learns that the draft it left
    behind is still there. Any authenticated user may read it; what an
    administrator additionally gets is their own drafts, because a draft is
    unpublished and private and a non-administrator's empty list is the same
    answer as having none.
    """
    if (refusal := _gate(msg)) is not None:
        return refusal
    library = await _library(hass, coordinator)
    try:
        snapshot = await library.async_snapshot(_actor(msg))
    except Unauthorized as error:
        return _unauthorized(error)
    return _ok(library=snapshot)


# ---------------------------------------------------------------------------
# Opening one
# ---------------------------------------------------------------------------


async def websocket_open_label_template_draft(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> dict[str, Any]:
    """Resume this administrator's untitled draft for one stock, or start one.

    Resume rather than create, because creating is destructive here: one
    untitled draft per administrator and Label Size *is* the store's slot, so
    an editor that opened by creating would throw away the work it was
    reopening on every reload. `resumed` says which happened, so the editor
    can tell its user it came back to unsaved work instead of silently showing
    something other than the Factory Template they clicked.
    """
    if (refusal := _gate(msg)) is not None:
        return refusal
    library = await _library(hass, coordinator)
    reference = msg.get("derive_from")
    try:
        draft, resumed = await library.async_open_editing_draft(
            _actor(msg),
            **_slot(msg),
            derive_from=TemplateRef.from_dict(reference) if reference else None,
        )
    except Unauthorized as error:
        return _unauthorized(error)
    except UnsupportedLabelSize as error:
        return _refused(
            CODE_UNKNOWN_LABEL_SIZE,
            str(error),
            RECOVERY_REFRESH_CAPABILITY,
            label_size_id=msg["label_size_id"],
        )
    except LabelSizeImmutable as error:
        return _refused(
            CODE_LABEL_SIZE_IMMUTABLE, str(error), RECOVERY_CHOOSE_ANOTHER_SIZE
        )
    except TemplateNotFound as error:
        return _refused(
            CODE_TEMPLATE_NOT_FOUND, str(error), RECOVERY_REFRESH_CAPABILITY
        )

    return _ok(draft=draft.as_dict(), resumed=resumed)


# ---------------------------------------------------------------------------
# Keeping it
# ---------------------------------------------------------------------------


async def websocket_autosave_label_template_draft(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> dict[str, Any]:
    """Store whatever the editor last had, valid or not, and say what is wrong.

    Never refused on content: half of editing passes through states that do
    not validate, and an autosave that dropped them would make every
    diagnostic a threat to the work. What comes back beside the stored draft
    is the publication check, so the editor can name why Publish is
    unavailable instead of guessing.

    It *is* refused on version. `expected_version` makes the save a
    compare-and-swap, which is what stops one administrator's second client
    from writing over the first one's newer work.
    """
    if (refusal := _gate(msg)) is not None:
        return refusal
    template_id = msg.get("template_id")
    extra: dict[str, Any] = {}
    if "name" in msg:
        if template_id is not None:
            # Renaming a published Label Template is its own operation, on the
            # template. A name arriving on a template-bound autosave is a
            # client that has confused the two, and performing either guess
            # would be worse than saying so.
            return _refused(
                CODE_NAME_NOT_ON_DRAFT,
                "A template-bound Template Draft carries no name: renaming a "
                "Label Template is its own operation.",
                RECOVERY_NONE,
                template_id=template_id,
            )
        extra["name"] = msg["name"]

    library = await _library(hass, coordinator)
    try:
        saved = await library.async_autosave_draft(
            _actor(msg),
            **_slot(msg),
            document=msg["document"],
            expected_version=msg.get("expected_version"),
            **extra,
        )
    except Unauthorized as error:
        return _unauthorized(error)
    except DraftVersionConflict as error:
        return _conflict(error)
    except DraftIsOrphaned as error:
        return _refused(
            CODE_DRAFT_ORPHANED,
            str(error),
            RECOVERY_REOPEN_DRAFT,
            template_id=error.template_id,
        )
    except DraftNotFound as error:
        return _refused(CODE_DRAFT_NOT_FOUND, str(error), RECOVERY_REOPEN_DRAFT)

    return _ok(**saved.as_dict())


# ---------------------------------------------------------------------------
# Looking at it
# ---------------------------------------------------------------------------


async def websocket_preview_label_template_draft(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> dict[str, Any]:
    """Render this administrator's own draft, through the canonical path.

    The same call a print makes with one argument different, so what the
    editor is looking at is the bitmap the printer would receive rather than a
    drawing of the layout.

    `expected_draft_version` is what makes the picture trustworthy. A render
    is expensive and an editor is fast, so by the time one comes back the
    draft may already have moved; answering anyway would put a raster of an
    older layout under geometry that has since changed, and nothing on screen
    would say so. Refusing instead leaves the editor with a stale raster it
    knows is stale, which is the honest state.
    """
    if (refusal := _gate(msg)) is not None:
        return refusal

    locale = msg["locale"]
    if locale not in SUPPORTED_LOCALES:
        return _refused(
            CODE_UNSUPPORTED_LOCALE,
            f"{locale} is not a supported print locale",
            RECOVERY_NONE,
            locale=locale,
        )
    subject = representative_subject(msg["fixture_family"], PrintContext.STRAIN)
    if subject is None:
        return _refused(
            CODE_UNKNOWN_FIXTURE,
            f"No {msg['fixture_family']} fixture is shipped for strain content",
            RECOVERY_REFRESH_CAPABILITY,
        )

    label_size_id = msg["label_size_id"]
    if not profiles_for_size(label_size_id):
        # Asked before rendering rather than caught afterwards: no
        # characterised printer can put this stock on paper, the answer costs
        # no round trip through the renderer, and the alternative is one
        # `HomeAssistantError` indistinguishable from a real render failure.
        return _refused(
            CODE_NO_CAPABILITY_PROFILE,
            f"No Capability Profile can render {label_size_id}",
            RECOVERY_CHOOSE_ANOTHER_SIZE,
            label_size_id=label_size_id,
        )

    library = await _library(hass, coordinator)
    expected = msg["expected_draft_version"]
    try:
        result = await library.async_preview_draft(
            _actor(msg),
            **_slot(msg),
            subject=subject,
            density=msg["density"],
            expected_version=expected,
        )
    except Unauthorized as error:
        return _unauthorized(error)
    except DraftVersionConflict as error:
        # The draft moved while this render was being asked for. Answering
        # anyway would put a raster of an older layout under geometry that has
        # since changed, with nothing on screen saying so.
        return _refused(
            CODE_DRAFT_VERSION_MISMATCH,
            str(error),
            RECOVERY_RELOAD_DRAFT,
            expected_version=error.expected,
            found_version=error.found,
        )
    except DraftNotPublishable as error:
        # An invalid layout cannot be compiled at all, so there is no
        # approximate picture to offer. The diagnostics are the answer, and
        # each one names the element the editor should select.
        return _refused(
            CODE_DRAFT_NOT_PUBLISHABLE,
            str(error),
            RECOVERY_FIX_LAYOUT,
            draft_version=expected,
            diagnostics=[item.as_dict() for item in error.diagnostics],
        )
    except DraftNotFound as error:
        return _refused(CODE_DRAFT_NOT_FOUND, str(error), RECOVERY_REOPEN_DRAFT)

    return _ok(
        draft_version=expected,
        label_size_id=label_size_id,
        fixture_family=msg["fixture_family"],
        subject=subject.id,
        render=result.as_dict(),
    )


# ---------------------------------------------------------------------------
# Publishing it
# ---------------------------------------------------------------------------


async def websocket_publish_label_template_draft(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> dict[str, Any]:
    """Turn one untitled draft into a Named Template, in one commit.

    Three refusals, and none of them costs the draft. An unnamed or
    duplicate-named draft is waiting on a decision its owner has not made yet;
    an invalid one is waiting on a layout fix; a stale one has been overtaken
    by somebody else's revision and must not be appended over it. All three
    leave the work exactly where it was, which is what "invalid or stale work
    remains preserved and recoverable" is made of.
    """
    if (refusal := _gate(msg)) is not None:
        return refusal
    library = await _library(hass, coordinator)
    try:
        publication = await library.async_publish_draft(
            _actor(msg),
            **_slot(msg),
            draft_id=msg.get("draft_id"),
            idempotency_key=msg.get("idempotency_key"),
        )
    except Unauthorized as error:
        return _unauthorized(error)
    except TemplateNameRequired as error:
        return _refused(CODE_NAME_REQUIRED, str(error), RECOVERY_RENAME)
    except DuplicateTemplateName as error:
        return _refused(
            CODE_DUPLICATE_NAME,
            str(error),
            RECOVERY_RENAME,
            name=error.name,
            label_size_id=error.label_size_id,
            template_id=error.template_id,
        )
    except DraftNotPublishable as error:
        return _refused(
            CODE_DRAFT_NOT_PUBLISHABLE,
            str(error),
            RECOVERY_FIX_LAYOUT,
            diagnostics=[item.as_dict() for item in error.diagnostics],
        )
    except DraftIsStale as error:
        return _refused(
            CODE_DRAFT_STALE,
            str(error),
            RECOVERY_RELOAD_DRAFT,
            template_id=error.template_id,
            base_revision=error.base_revision,
            head_revision=error.head,
        )
    except DraftNotFound as error:
        return _refused(CODE_DRAFT_NOT_FOUND, str(error), RECOVERY_REOPEN_DRAFT)

    return _ok(**publication.as_dict())


# ---------------------------------------------------------------------------
# Throwing it away, on purpose
# ---------------------------------------------------------------------------


async def websocket_discard_label_template_draft(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> dict[str, Any]:
    """Remove unpublished work explicitly, and hand back what was removed.

    The removed draft travels back whole because an editor that has just
    thrown work away is the one place an undo can still be offered.
    """
    if (refusal := _gate(msg)) is not None:
        return refusal
    library = await _library(hass, coordinator)
    try:
        discarded = await library.async_discard_draft(_actor(msg), **_slot(msg))
    except Unauthorized as error:
        return _unauthorized(error)
    except DraftNotFound as error:
        return _refused(CODE_DRAFT_NOT_FOUND, str(error), RECOVERY_REOPEN_DRAFT)

    return _ok(**discarded.as_dict())


COMMANDS: list[WSCommand] = [
    WSCommand(
        WS_TYPE_GET_LABEL_TEMPLATE_LIBRARY,
        websocket_get_label_template_library,
        SCHEMA_WS_GET_LABEL_TEMPLATE_LIBRARY,
        resolve="any",
        actor=True,
    ),
    WSCommand(
        WS_TYPE_OPEN_LABEL_TEMPLATE_DRAFT,
        websocket_open_label_template_draft,
        SCHEMA_WS_OPEN_LABEL_TEMPLATE_DRAFT,
        resolve="any",
        actor=True,
    ),
    WSCommand(
        WS_TYPE_AUTOSAVE_LABEL_TEMPLATE_DRAFT,
        websocket_autosave_label_template_draft,
        SCHEMA_WS_AUTOSAVE_LABEL_TEMPLATE_DRAFT,
        resolve="any",
        actor=True,
    ),
    WSCommand(
        WS_TYPE_PREVIEW_LABEL_TEMPLATE_DRAFT,
        websocket_preview_label_template_draft,
        SCHEMA_WS_PREVIEW_LABEL_TEMPLATE_DRAFT,
        resolve="any",
        actor=True,
    ),
    WSCommand(
        WS_TYPE_PUBLISH_LABEL_TEMPLATE_DRAFT,
        websocket_publish_label_template_draft,
        SCHEMA_WS_PUBLISH_LABEL_TEMPLATE_DRAFT,
        resolve="any",
        actor=True,
    ),
    WSCommand(
        WS_TYPE_DISCARD_LABEL_TEMPLATE_DRAFT,
        websocket_discard_label_template_draft,
        SCHEMA_WS_DISCARD_LABEL_TEMPLATE_DRAFT,
        resolve="any",
        actor=True,
    ),
]

__all__ = [
    "COMMANDS",
    "WS_TYPE_AUTOSAVE_LABEL_TEMPLATE_DRAFT",
    "WS_TYPE_DISCARD_LABEL_TEMPLATE_DRAFT",
    "WS_TYPE_GET_LABEL_TEMPLATE_LIBRARY",
    "WS_TYPE_OPEN_LABEL_TEMPLATE_DRAFT",
    "WS_TYPE_PREVIEW_LABEL_TEMPLATE_DRAFT",
    "WS_TYPE_PUBLISH_LABEL_TEMPLATE_DRAFT",
]
