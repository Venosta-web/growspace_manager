"""TDD tests for print_label field visibility, density, and QR target (issue #401)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.services.strain_library import (
    handle_print_label,
)
from homeassistant.core import HomeAssistant, ServiceCall


@pytest.fixture
def mock_hass() -> MagicMock:
    hass = MagicMock(spec=HomeAssistant)
    hass.config = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock(return_value={"status": "ok"})
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    return hass


@pytest.fixture
def mock_coordinator() -> MagicMock:
    coordinator = MagicMock()
    coordinator.plants = {}
    return coordinator


@pytest.fixture
def mock_strain_library() -> MagicMock:
    lib = MagicMock()
    lib.load = AsyncMock()
    lib.get_all = MagicMock(return_value={})
    return lib


def _make_call(data: dict) -> MagicMock:
    call = MagicMock(spec=ServiceCall)
    call.data = data
    return call


def _niimbot_payload(mock_hass: MagicMock) -> list[dict]:
    """Extract the Niimbot payload from the last async_call invocation."""
    service_data = mock_hass.services.async_call.call_args.args[2]
    return service_data["payload"]


def _niimbot_density(mock_hass: MagicMock) -> int:
    service_data = mock_hass.services.async_call.call_args.args[2]
    return service_data["density"]


# ---------------------------------------------------------------------------
# Tracer bullet: logo field
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_logo_excluded_when_fields_logo_false(
    mock_hass: MagicMock,
    mock_coordinator: MagicMock,
    mock_strain_library: MagicMock,
) -> None:
    """Logo dlimg element is omitted when fields['logo'] is False."""
    with patch(
        "custom_components.growspace_manager.services.strain_library.get_url",
        return_value="http://ha.local",
    ):
        call = _make_call(
            {
                "strain": "Vitamin Z",
                "breeder_logo": "data:image/png;base64,abc",
                "fields": {"logo": False},
            }
        )
        await handle_print_label(mock_hass, mock_coordinator, mock_strain_library, call)

    payload = _niimbot_payload(mock_hass)
    types = [el["type"] for el in payload]
    assert "dlimg" not in types


# ---------------------------------------------------------------------------
# Field visibility: QR code
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_qr_excluded_when_fields_qr_false(
    mock_hass: MagicMock,
    mock_coordinator: MagicMock,
    mock_strain_library: MagicMock,
) -> None:
    """QR element is omitted when fields['qr'] is False."""
    plant = MagicMock()
    plant.genetics.strain_name = "Vitamin Z"
    plant.genetics.phenotype_name = "S1"
    mock_coordinator.plants = {"p1": plant}

    with patch(
        "custom_components.growspace_manager.services.strain_library.get_url",
        return_value="http://ha.local",
    ):
        call = _make_call({"plant_id": "p1", "fields": {"qr": False}})
        await handle_print_label(mock_hass, mock_coordinator, mock_strain_library, call)

    payload = _niimbot_payload(mock_hass)
    assert all(el["type"] != "qrcode" for el in payload)


@pytest.mark.asyncio
async def test_qr_included_by_default_when_plant_id_present(
    mock_hass: MagicMock,
    mock_coordinator: MagicMock,
    mock_strain_library: MagicMock,
) -> None:
    """QR element is present when fields map is absent (backwards compat)."""
    plant = MagicMock()
    plant.genetics.strain_name = "Vitamin Z"
    plant.genetics.phenotype_name = "S1"
    mock_coordinator.plants = {"p1": plant}

    with patch(
        "custom_components.growspace_manager.services.strain_library.get_url",
        return_value="http://ha.local",
    ):
        call = _make_call({"plant_id": "p1"})
        await handle_print_label(mock_hass, mock_coordinator, mock_strain_library, call)

    payload = _niimbot_payload(mock_hass)
    assert any(el["type"] == "qrcode" for el in payload)


# ---------------------------------------------------------------------------
# Field visibility: multiline info rows (phenotype, breeder, lineage)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_phenotype_excluded_from_multiline_when_fields_phenotype_false(
    mock_hass: MagicMock,
    mock_coordinator: MagicMock,
    mock_strain_library: MagicMock,
) -> None:
    """Phenotype line absent from multiline block when fields['phenotype'] is False."""
    with patch(
        "custom_components.growspace_manager.services.strain_library.get_url",
        return_value="http://ha.local",
    ):
        call = _make_call(
            {
                "strain": "Vitamin Z",
                "phenotype": "S1",
                "fields": {"phenotype": False},
            }
        )
        await handle_print_label(mock_hass, mock_coordinator, mock_strain_library, call)

    payload = _niimbot_payload(mock_hass)
    multiline = next(
        (el for el in payload if el["type"] == "new_multiline" and el.get("y") == 100),
        None,
    )
    assert multiline is not None
    assert "S1" not in multiline.get("value", "")


@pytest.mark.asyncio
async def test_logo_included_by_default_when_breeder_logo_present(
    mock_hass: MagicMock,
    mock_coordinator: MagicMock,
    mock_strain_library: MagicMock,
) -> None:
    """Logo element present when fields map absent and breeder_logo is provided."""
    with patch(
        "custom_components.growspace_manager.services.strain_library.get_url",
        return_value="http://ha.local",
    ):
        call = _make_call(
            {
                "strain": "Vitamin Z",
                "breeder_logo": "data:image/png;base64,abc",
            }
        )
        await handle_print_label(mock_hass, mock_coordinator, mock_strain_library, call)

    payload = _niimbot_payload(mock_hass)
    assert any(el["type"] == "dlimg" for el in payload)


# ---------------------------------------------------------------------------
# Density mapping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_density_low_maps_to_3(
    mock_hass: MagicMock,
    mock_coordinator: MagicMock,
    mock_strain_library: MagicMock,
) -> None:
    with patch(
        "custom_components.growspace_manager.services.strain_library.get_url",
        return_value="http://ha.local",
    ):
        call = _make_call({"strain": "Vitamin Z", "density": "low"})
        await handle_print_label(mock_hass, mock_coordinator, mock_strain_library, call)

    assert _niimbot_density(mock_hass) == 3


@pytest.mark.asyncio
async def test_density_normal_maps_to_5(
    mock_hass: MagicMock,
    mock_coordinator: MagicMock,
    mock_strain_library: MagicMock,
) -> None:
    with patch(
        "custom_components.growspace_manager.services.strain_library.get_url",
        return_value="http://ha.local",
    ):
        call = _make_call({"strain": "Vitamin Z", "density": "normal"})
        await handle_print_label(mock_hass, mock_coordinator, mock_strain_library, call)

    assert _niimbot_density(mock_hass) == 5


@pytest.mark.asyncio
async def test_density_high_maps_to_8(
    mock_hass: MagicMock,
    mock_coordinator: MagicMock,
    mock_strain_library: MagicMock,
) -> None:
    with patch(
        "custom_components.growspace_manager.services.strain_library.get_url",
        return_value="http://ha.local",
    ):
        call = _make_call({"strain": "Vitamin Z", "density": "high"})
        await handle_print_label(mock_hass, mock_coordinator, mock_strain_library, call)

    assert _niimbot_density(mock_hass) == 8


@pytest.mark.asyncio
async def test_density_defaults_to_5_when_absent(
    mock_hass: MagicMock,
    mock_coordinator: MagicMock,
    mock_strain_library: MagicMock,
) -> None:
    with patch(
        "custom_components.growspace_manager.services.strain_library.get_url",
        return_value="http://ha.local",
    ):
        call = _make_call({"strain": "Vitamin Z"})
        await handle_print_label(mock_hass, mock_coordinator, mock_strain_library, call)

    assert _niimbot_density(mock_hass) == 5


# ---------------------------------------------------------------------------
# QR target URL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_qr_target_web_uses_ha_base_url(
    mock_hass: MagicMock,
    mock_coordinator: MagicMock,
    mock_strain_library: MagicMock,
) -> None:
    """qr_target='web' encodes {ha_base_url}/plant/{plant_id}."""
    plant = MagicMock()
    plant.genetics.strain_name = "Vitamin Z"
    plant.genetics.phenotype_name = "S1"
    mock_coordinator.plants = {"p1": plant}

    with patch(
        "custom_components.growspace_manager.services.strain_library.get_url",
        return_value="http://ha.local",
    ):
        call = _make_call({"plant_id": "p1", "qr_target": "web"})
        await handle_print_label(mock_hass, mock_coordinator, mock_strain_library, call)

    payload = _niimbot_payload(mock_hass)
    qr = next(el for el in payload if el["type"] == "qrcode")
    assert qr["data"] == "http://ha.local/plant/p1"


@pytest.mark.asyncio
async def test_qr_target_deeplink_uses_ha_scheme(
    mock_hass: MagicMock,
    mock_coordinator: MagicMock,
    mock_strain_library: MagicMock,
) -> None:
    """qr_target='deeplink' encodes homeassistant://navigate/growspace/plant/{plant_id}."""
    plant = MagicMock()
    plant.genetics.strain_name = "Vitamin Z"
    plant.genetics.phenotype_name = "S1"
    mock_coordinator.plants = {"p1": plant}

    with patch(
        "custom_components.growspace_manager.services.strain_library.get_url",
        return_value="http://ha.local",
    ):
        call = _make_call({"plant_id": "p1", "qr_target": "deeplink"})
        await handle_print_label(mock_hass, mock_coordinator, mock_strain_library, call)

    payload = _niimbot_payload(mock_hass)
    qr = next(el for el in payload if el["type"] == "qrcode")
    assert qr["data"] == "homeassistant://navigate/growspace/plant/p1"


@pytest.mark.asyncio
async def test_qr_target_absent_defaults_to_web_url(
    mock_hass: MagicMock,
    mock_coordinator: MagicMock,
    mock_strain_library: MagicMock,
) -> None:
    """No qr_target → falls back to web URL (backwards compat)."""
    plant = MagicMock()
    plant.genetics.strain_name = "Vitamin Z"
    plant.genetics.phenotype_name = "S1"
    mock_coordinator.plants = {"p1": plant}

    with patch(
        "custom_components.growspace_manager.services.strain_library.get_url",
        return_value="http://ha.local",
    ):
        call = _make_call({"plant_id": "p1"})
        await handle_print_label(mock_hass, mock_coordinator, mock_strain_library, call)

    payload = _niimbot_payload(mock_hass)
    qr = next(el for el in payload if el["type"] == "qrcode")
    assert qr["data"].startswith("http://ha.local")
