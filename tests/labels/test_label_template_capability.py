"""The complete Label Template capability publication boundary (issue #223)."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from custom_components.growspace_manager.labels.canonical import (
    CAPABILITY_GENERATION,
    FACTORY_50X30,
    FACTORY_TEMPLATES,
    LABEL_SIZES,
    PROFILES,
)
from custom_components.growspace_manager.labels.capability import (
    CAPABILITY_FAMILY,
    CONTRACT_MAJOR,
    REQUIRED_OPERATIONS,
    IncompatibleLabelTemplateContract,
    capability_errors,
    contract_identity,
    published_capability,
    require_contract,
)
from custom_components.growspace_manager.labels.library import (
    FACTORY_FALLBACK,
    Actor,
    LabelTemplateLibrary,
)
from custom_components.growspace_manager.websocket.labels import (
    COMMANDS,
    WS_TYPE_GET_LABEL_TEMPLATE_CAPABILITY,
    websocket_get_label_template_capability,
)
from homeassistant.exceptions import HomeAssistantError

FIXTURE_PATH = (
    Path(__file__).parent.parent
    / "fixtures"
    / "contract"
    / "label_template_capability_v1.json"
)


def test_the_complete_capability_passes_its_own_audit() -> None:
    assert capability_errors() == ()
    capability = published_capability()
    assert capability is not None
    value = capability.as_dict()
    assert value["contract"] == contract_identity()
    assert value["contract"]["family"] == CAPABILITY_FAMILY
    assert value["contract"]["major"] == CONTRACT_MAJOR
    assert value["contract"]["generation"] == CAPABILITY_GENERATION
    assert tuple(value["operations"]) == REQUIRED_OPERATIONS
    assert all(item["available"] for item in value["operations"].values())


def test_every_catalogued_size_has_exactly_one_valid_factory_fallback() -> None:
    capability = published_capability()
    assert capability is not None
    factories = capability.as_dict()["catalogues"]["factory_templates"]
    assert {item["label_size_id"] for item in factories} == set(LABEL_SIZES)
    assert len(factories) == len(LABEL_SIZES) == len(FACTORY_TEMPLATES)
    assert len({item["layout_digest"] for item in factories}) == len(factories)
    assert all(
        item["layout"]["label_size_id"] == item["label_size_id"] for item in factories
    )


def test_the_slim_factory_is_composed_for_its_stock_not_scaled_from_50x30() -> None:
    slim = next(
        item
        for item in FACTORY_TEMPLATES.values()
        if item.label_size_id == "growspace.stock.50x15.v1"
    )
    assert len(slim.layout.elements) < len(FACTORY_50X30.layout.elements)
    assert slim.layout.elements[0].frame.height_mm == 5.0
    assert FACTORY_50X30.layout.elements[0].frame.height_mm == 8.4


@pytest.mark.asyncio
async def test_reopening_a_library_keeps_factory_fallbacks_idempotent(
    hass: Any,
) -> None:
    first = LabelTemplateLibrary(hass, "factory-idempotency")
    second = LabelTemplateLibrary(hass, "factory-idempotency")
    await first.async_load()
    await second.async_load()
    viewer = Actor(user_id="viewer", is_admin=False)

    for size_id in LABEL_SIZES:
        resolved = await second.async_resolve_default(viewer, size_id)
        assert resolved.via == FACTORY_FALLBACK
        assert resolved.layout.label_size_id == size_id
    assert second.state.templates == {}
    assert second.state.defaults == {}


def test_a_missing_operation_suppresses_the_whole_capability() -> None:
    from custom_components.growspace_manager.labels import capability as module

    partial = dict(module._IMPLEMENTATIONS)
    partial.pop("batch_retry")
    assert published_capability(implementations=partial) is None
    assert "missing=['batch_retry']" in capability_errors(implementations=partial)[0]


def test_an_extra_or_non_callable_operation_suppresses_the_capability() -> None:
    from custom_components.growspace_manager.labels import capability as module

    inconsistent = dict(module._IMPLEMENTATIONS)
    inconsistent["future"] = (lambda: None,)
    inconsistent["preview"] = (None,)  # type: ignore[assignment]
    errors = capability_errors(implementations=inconsistent)
    assert "extra=['future']" in errors[0]
    assert "operation preview has no complete implementation" in errors


def test_an_invalid_factory_suppresses_the_whole_capability() -> None:
    broken = replace(
        FACTORY_50X30,
        document={"schema": "growspace.label-layout"},
    )
    factories = dict(FACTORY_TEMPLATES)
    factories[broken.id] = broken
    assert published_capability(factories=factories) is None
    assert any("invalid" in error for error in capability_errors(factories=factories))


def test_every_factory_catalogue_inconsistency_is_named() -> None:
    unknown = replace(
        FACTORY_50X30,
        id="growspace.factory.unknown",
        label_size_id="growspace.stock.unknown.v1",
    )
    mismatched = replace(
        FACTORY_50X30,
        id="growspace.factory.mismatched",
        label_size_id="growspace.stock.40x30.v1",
    )
    factories = {
        **FACTORY_TEMPLATES,
        "wrong-key": unknown,
        mismatched.id: mismatched,
    }
    factories.pop("growspace.factory.50x15")
    errors = capability_errors(factories=factories)
    assert any("key wrong-key does not match" in error for error in errors)
    assert any("names an unknown Label Size" in error for error in errors)
    assert any("document names another stock" in error for error in errors)
    assert any("50x15.v1 has 0 factory fallbacks" in error for error in errors)
    assert any("40x30.v1 has 2 factory fallbacks" in error for error in errors)


def test_an_inconsistent_profile_suppresses_the_capability() -> None:
    from custom_components.growspace_manager.labels import capability as module

    profile = next(iter(PROFILES.values()))
    with patch.object(module, "PROFILES", {"wrong-key": profile}):
        assert any(
            "Capability Profile wrong-key is internally inconsistent" in error
            for error in capability_errors()
        )
        assert published_capability() is None


def test_the_capability_has_one_discovery_command() -> None:
    assert [command.type for command in COMMANDS].count(
        WS_TYPE_GET_LABEL_TEMPLATE_CAPABILITY
    ) == 1
    assert COMMANDS[0].type == WS_TYPE_GET_LABEL_TEMPLATE_CAPABILITY
    payload = websocket_get_label_template_capability(None, None, {})  # type: ignore[arg-type]
    assert payload["contract"] == contract_identity()


def test_discovery_refuses_to_publish_a_partial_capability() -> None:
    with (
        patch(
            "custom_components.growspace_manager.websocket.labels.published_capability",
            return_value=None,
        ),
        pytest.raises(HomeAssistantError, match="capability is unavailable"),
    ):
        websocket_get_label_template_capability(None, None, {})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("received", "reason"),
    [
        (None, "missing"),
        ({"family": "some.future.family", "major": 1, "generation": 3}, "unknown"),
        ({"family": CAPABILITY_FAMILY, "major": 99, "generation": 3}, "unknown"),
        ({"family": CAPABILITY_FAMILY, "major": 1, "generation": 2}, "stale"),
    ],
)
def test_new_commands_reject_missing_unknown_and_stale_contracts(
    received: object, reason: str
) -> None:
    with pytest.raises(IncompatibleLabelTemplateContract) as refused:
        require_contract(received)
    assert refused.value.as_dict()["reason"] == reason
    assert refused.value.as_dict()["recovery"] == "refresh_capability"


def test_the_current_contract_is_accepted() -> None:
    require_contract(contract_identity())


def test_the_shared_capability_fixture_is_exact(pytestconfig: pytest.Config) -> None:
    capability = published_capability()
    assert capability is not None
    value = capability.as_dict()
    if pytestconfig.getoption("regenerate_contract_fixture"):
        FIXTURE_PATH.write_text(
            f"{json.dumps(value, indent=2, sort_keys=True)}\n", encoding="utf-8"
        )
    assert FIXTURE_PATH.exists()
    assert value == json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
