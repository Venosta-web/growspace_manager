"""Label Template capability discovery, and the one read-only preview beside it.

Two commands, and the difference between them is the whole compatibility
policy. Discovery is unconditional: a card that does not yet know what this
backend is has to be able to ask. Everything else is contract-gated, so a
card holding a stale or foreign contract identity is refused *before* an
operation starts rather than served a result it would misread.

The preview command renders a **shipped Factory Template** and nothing else.
It reads no library, writes no store, mints no revision and creates no draft:
a card entering the template path needs one authoritative raster to show
before there is any user template to show, and that raster must not cost the
user a template they did not ask for.

A refusal comes back as a *result*, not as a transport error. The card has to
tell "your contract is stale, refresh it" from "this stock has no printer
profile" from "the renderer failed", and act differently on each; Home
Assistant's error frame carries a code and a sentence, which is enough for
none of them. So every refusal is one structured row with its own code and
the recovery that actually applies.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.labels.canonical import (
    DEFAULT_LABEL_SIZE_ID,
    SUPPORTED_LOCALES,
    TYPICAL,
    PrintContext,
    async_render_factory_preview,
    factory_template_for_size,
    profiles_for_size,
    representative_subject,
)
from custom_components.growspace_manager.labels.capability import (
    IncompatibleLabelTemplateContract,
    contract_identity,
    published_capability,
    require_contract,
)
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
import homeassistant.util.dt as dt_util

from ._common import WSCommand

WS_TYPE_GET_LABEL_TEMPLATE_CAPABILITY = f"{DOMAIN}/get_label_template_capability"
WS_TYPE_PREVIEW_LABEL_FACTORY_TEMPLATE = f"{DOMAIN}/preview_label_factory_template"

SCHEMA_WS_GET_LABEL_TEMPLATE_CAPABILITY = (
    websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
        {vol.Required("type"): WS_TYPE_GET_LABEL_TEMPLATE_CAPABILITY}
    )
)

SCHEMA_WS_PREVIEW_LABEL_FACTORY_TEMPLATE = (
    websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
        {
            vol.Required("type"): WS_TYPE_PREVIEW_LABEL_FACTORY_TEMPLATE,
            # Deliberately untyped beyond "a mapping": a stale or foreign
            # identity is the case this command exists to refuse legibly, and
            # a schema rejection would turn it into a validation error with
            # nothing in it for the card to act on.
            vol.Required("contract"): dict,
            vol.Optional("label_size_id", default=DEFAULT_LABEL_SIZE_ID): str,
            vol.Optional("context", default=str(PrintContext.STRAIN)): str,
            vol.Optional("fixture_family", default=TYPICAL): str,
            vol.Optional("density", default="normal"): str,
            vol.Optional("locale", default=SUPPORTED_LOCALES[0]): str,
        }
    )
)

#: A refusal the card can act on, rather than one it can only display.
RECOVERY_REFRESH_CAPABILITY = "refresh_capability"
RECOVERY_CHOOSE_ANOTHER_SIZE = "choose_another_label_size"
RECOVERY_NONE = "none"

RENDERED = "rendered"
REFUSED = "refused"


def websocket_get_label_template_capability(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> dict[str, Any]:
    """Return the one complete envelope; never a partial capability."""
    del hass, coordinator, msg
    capability = published_capability()
    if capability is None:
        raise HomeAssistantError("The Label Template capability is unavailable")
    return capability.as_dict()


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


async def websocket_preview_label_factory_template(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> dict[str, Any]:
    """Render one shipped Factory Template against one representative subject.

    Read-only in the strongest sense available: the layout comes from the
    shipped catalogue, the subject from the shipped fixtures, and neither the
    template library nor the calibration ledger is opened at all. Nothing this
    command does can be mistaken afterwards for something a user authored.
    """
    del coordinator
    try:
        require_contract(msg["contract"])
    except IncompatibleLabelTemplateContract as refused:
        return {"outcome": REFUSED, "refusal": refused.as_dict()}

    label_size_id = msg["label_size_id"]
    template = factory_template_for_size(label_size_id)
    if template is None:
        return _refused(
            "label_template.unknown_label_size",
            f"No Factory Template is shipped for {label_size_id}",
            RECOVERY_REFRESH_CAPABILITY,
            label_size_id=label_size_id,
        )

    profiles = profiles_for_size(label_size_id)
    if not profiles:
        return _refused(
            "label_template.no_capability_profile",
            f"No Capability Profile can render {label_size_id}",
            RECOVERY_CHOOSE_ANOTHER_SIZE,
            label_size_id=label_size_id,
        )

    locale = msg["locale"]
    if locale not in SUPPORTED_LOCALES:
        return _refused(
            "label_template.unsupported_locale",
            f"{locale} is not a supported print locale",
            RECOVERY_NONE,
            locale=locale,
        )

    try:
        context = PrintContext(msg["context"])
    except ValueError:
        return _refused(
            "label_template.unknown_print_context",
            f"{msg['context']} is not a print context",
            RECOVERY_REFRESH_CAPABILITY,
        )

    family = msg["fixture_family"]
    subject = representative_subject(family, context)
    if subject is None:
        return _refused(
            "label_template.unknown_fixture",
            f"No {family} fixture is shipped for {context}",
            RECOVERY_REFRESH_CAPABILITY,
        )

    result = await async_render_factory_preview(
        hass,
        content=subject.snapshot(
            as_of=dt_util.utcnow(),
            locale=locale,
            time_zone=hass.config.time_zone or "UTC",
        ),
        label_size_id=label_size_id,
        template=template,
        profile=profiles[0],
        density=msg["density"],
    )
    return {
        "outcome": RENDERED,
        "contract": contract_identity(),
        "template": {
            "id": template.id,
            "revision": template.revision,
            "name": template.name,
            "label_size_id": template.label_size_id,
            "layout_digest": template.layout.digest,
        },
        "subject": subject.id,
        "fixture_family": family,
        "render": result.as_dict(),
    }


COMMANDS: list[WSCommand] = [
    WSCommand(
        WS_TYPE_GET_LABEL_TEMPLATE_CAPABILITY,
        websocket_get_label_template_capability,
        SCHEMA_WS_GET_LABEL_TEMPLATE_CAPABILITY,
        resolve="any",
        sync=True,
    ),
    WSCommand(
        WS_TYPE_PREVIEW_LABEL_FACTORY_TEMPLATE,
        websocket_preview_label_factory_template,
        SCHEMA_WS_PREVIEW_LABEL_FACTORY_TEMPLATE,
        resolve="any",
    ),
]
