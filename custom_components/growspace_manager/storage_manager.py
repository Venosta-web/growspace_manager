"""Storage manager for Growspace Manager."""

from __future__ import annotations

from dataclasses import asdict
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    STORAGE_KEY,
    STORAGE_KEY_CONFIG,
    STORAGE_KEY_GENETICS,
    STORAGE_KEY_PLANTS,
    STORAGE_VERSION,
)
from .models import (
    ECRampCurve,
    EnvironmentConfig,
    Growspace,
    IPMPreset,
    NutrientInventory,
    NutrientPreset,
    Plant,
    PollinationEvent,
    SeedBatch,
)

if TYPE_CHECKING:
    from .data_access.growspace_repository import GrowspaceRepository
    from .data_access.notification_state import NotificationState
    from .managers.genetics import GeneticsManager
    from .managers.nutrient import NutrientManager

_LOGGER = logging.getLogger(__name__)


class StorageManager:
    """Manages data persistence for the Growspace Manager."""

    def __init__(
        self,
        hass: HomeAssistant,
        repository: GrowspaceRepository,
        nutrient_manager: NutrientManager,
        genetics_manager: GeneticsManager | None = None,
        notification_state: NotificationState | None = None,
    ) -> None:
        """Initialize the StorageManager."""
        self.hass = hass
        self.repository = repository
        self.nutrient_manager = nutrient_manager
        self.genetics_manager = genetics_manager
        self.notification_state = notification_state

        # Segmented stores
        self.config_store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY_CONFIG
        )
        self.plants_store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY_PLANTS
        )
        self.genetics_store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY_GENETICS
        )

        # Legacy store for migration
        self.legacy_store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY
        )

    async def async_save(self) -> None:
        """Save the current state to persistent storage (debounced)."""
        # debounce delay of 10 seconds as requested
        self.config_store.async_delay_save(self._get_config_data, 10)
        self.plants_store.async_delay_save(self._get_plants_data, 10)
        if self.genetics_manager is not None:
            self.genetics_store.async_delay_save(self._get_genetics_data, 10)

    async def async_force_save(self) -> None:
        """Force save immediately (ignoring delay) to ensure data integrity."""
        await self.config_store.async_save(self._get_config_data())
        await self.plants_store.async_save(self._get_plants_data())
        if self.genetics_manager is not None:
            await self.genetics_store.async_save(self._get_genetics_data())

    def _get_config_data(self) -> dict[str, Any]:
        """Gather configuration data for storage."""
        # Use nutrient manager for serialization data
        nutrient_data = self.nutrient_manager.get_serialization_data()
        genetics_data = self.genetics_manager.get_serialization_data()

        config = {
            "growspaces": {
                gs.id: asdict(gs) for gs in self.repository.get_all_growspaces()
            },
            "notifications_sent": self.notification_state.sent if self.notification_state else {},
            "notifications_enabled": self.notification_state.enabled if self.notification_state else {},
        }
        # Merge nutrient data (presets and inventory)
        config.update(nutrient_data)
        # Merge genetics data (seed batches and pollination events)
        config.update(genetics_data)
        return config

    def _get_plants_data(self) -> dict[str, Any]:
        """Gather plant data for storage."""
        return {
            "plants": {p.plant_id: asdict(p) for p in self.repository.get_all_plants()},
        }

    def _get_genetics_data(self) -> dict[str, Any]:
        """Gather genetics data for storage."""
        if self.genetics_manager is None:
            return {}
        return self.genetics_manager.get_serialization_data()

    async def async_load(self, options: dict[str, Any] | None = None) -> None:
        """Load data from persistent storage and handle migrations."""
        config_data = await self.config_store.async_load()
        plants_data = await self.plants_store.async_load()
        genetics_data = await self.genetics_store.async_load()

        if config_data or plants_data:
            _LOGGER.info("Loading data from segmented storage")
            if config_data:
                self._load_config(config_data, options)
            if plants_data:
                self._load_plants(plants_data)
        else:
            # Fallback to legacy
            _LOGGER.info("Checking for legacy storage data")
            legacy_data = await self.legacy_store.async_load()
            if legacy_data:
                _LOGGER.info("Migrating from legacy storage found")
                self._load_legacy(legacy_data, options)

                # Perform immediate save to migrate to new structure
                await self.config_store.async_save(self._get_config_data())
                await self.plants_store.async_save(self._get_plants_data())
            else:
                _LOGGER.info("No stored data found, starting fresh")
                # Ensure files are created even if empty
                await self.async_save()

        if genetics_data and self.genetics_manager is not None:
            self._load_genetics(genetics_data)

    def _load_config(
        self, data: dict[str, Any], options: dict[str, Any] | None = None
    ) -> None:
        """Load configuration data."""
        self._load_growspaces(data, options)

        # Load nutrient data into manager
        nutrient_presets = self._load_nutrient_presets(data)
        ipm_presets = self._load_ipm_presets(data)
        inventory = self._load_nutrient_inventory(data)
        ec_ramp_curves = self._load_ec_ramp_curves(data)

        self.nutrient_manager.load_data(
            nutrient_presets, ipm_presets, inventory, ec_ramp_curves
        )

        # Load genetics data into manager
        seed_batches = {
            bid: SeedBatch.from_dict(b)
            for bid, b in data.get("seed_batches", {}).items()
        }
        pollination_events = {
            eid: PollinationEvent.from_dict(e)
            for eid, e in data.get("pollination_events", {}).items()
        }
        self.genetics_manager.load_data(seed_batches, pollination_events)

        # Load notification tracking
        if self.notification_state is not None:
            self.notification_state.sent = data.get("notifications_sent", {})
            self.notification_state.enabled = data.get("notifications_enabled", {})

            # Ensure all growspaces have a notification enabled state
            for growspace in self.repository.get_all_growspaces():
                if growspace.id not in self.notification_state.enabled:
                    self.notification_state.enabled[growspace.id] = True

    def _load_legacy(
        self, data: dict[str, Any], options: dict[str, Any] | None = None
    ) -> None:
        """Load from legacy single-file format."""
        # Legacy format had everything in one dict
        self._load_plants(data)  # Plants were top level "plants" key
        self._load_config(data, options)  # Config keys were also top level

    def _backup_corrupt_data(self, key: str, data: dict[str, Any]) -> None:
        """Backup corrupt data to a file before reset."""
        try:
            timestamp = dt_util.now().strftime("%Y%m%d_%H%M%S")
            backup_filename = f"growspace_manager_{key}_CORRUPT_{timestamp}.json"
            backup_path = Path(self.hass.config.path(".storage")) / backup_filename

            with backup_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)

            _LOGGER.critical(
                "Data corruption detected for %s. Raw data backed up to %s before reset",
                key,
                backup_path,
            )
        except (OSError, TypeError, ValueError):
            _LOGGER.exception("Failed to backup corrupt %s data", key)

    def _load_plants(self, data: dict[str, Any]) -> None:
        """Load plants from storage data.

        Uses mashumaro for deserialization. Plant.__pre_deserialize__ handles
        migrations (strain→genetics, row/col sanitization, stage_history building).
        """
        try:
            raw_plants = data.get("plants", {})
            plants: dict[str, Plant] = {}

            for pid, pdata in raw_plants.items():
                try:
                    if isinstance(pdata, dict):
                        # Mashumaro handles all migrations via __pre_deserialize__
                        plants[pid] = Plant.from_dict(pdata)
                    elif isinstance(pdata, Plant):
                        # Already a Plant instance
                        plants[pid] = pdata
                    else:
                        _LOGGER.error(
                            "Failed to load plant %s (invalid type: %s)",
                            pid,
                            type(pdata),
                        )
                except (ValueError, KeyError, TypeError):
                    _LOGGER.exception(
                        "Failed to load plant %s due to data structure mismatch", pid
                    )
                except Exception:
                    _LOGGER.exception("Unexpected error loading plant %s", pid)

            self.repository.load_plants(plants)
            _LOGGER.info("Loaded %d plants", len(plants))
        except (ValueError, KeyError, TypeError):
            _LOGGER.exception("Critical data structure error loading plants")
            self._backup_corrupt_data("plants", data)
            self.repository.load_plants({})
        except Exception:
            _LOGGER.exception("Unexpected error loading plants")
            self._backup_corrupt_data("plants", data)
            self.repository.load_plants({})

    def _load_growspaces(
        self, data: dict[str, Any], options: dict[str, Any] | None = None
    ) -> None:
        """Load growspaces from storage data.

        Uses mashumaro for deserialization. Growspace.__pre_deserialize__ handles
        migrations (rows/plants_per_row sanitization, irrigation_config migrations).
        """
        try:
            raw_growspaces = data.get("growspaces", {})
            growspaces: dict[str, Growspace] = {}

            for gid, gdata in raw_growspaces.items():
                try:
                    if isinstance(gdata, dict):
                        # Mashumaro handles all migrations via __pre_deserialize__
                        growspaces[gid] = Growspace.from_dict(gdata)
                    elif isinstance(gdata, Growspace):
                        # Already a Growspace instance
                        growspaces[gid] = gdata
                    else:
                        _LOGGER.error(
                            "Failed to load growspace %s (invalid type: %s)",
                            gid,
                            type(gdata),
                        )
                except (ValueError, KeyError, TypeError):
                    _LOGGER.exception(
                        "Failed to load growspace %s due to data structure mismatch",
                        gid,
                    )
                except Exception:
                    _LOGGER.exception("Unexpected error loading growspace %s", gid)

            self.repository.load_growspaces(growspaces)
            _LOGGER.info("Loaded %d growspaces", len(growspaces))

            self._apply_options_to_growspaces(options)
        except (ValueError, KeyError, TypeError):
            _LOGGER.exception("Critical data structure error loading growspaces")
            self._backup_corrupt_data("growspaces", data)
            self.repository.load_growspaces({})
        except Exception:
            _LOGGER.exception("Unexpected error loading growspaces")
            self._backup_corrupt_data("growspaces", data)
            self.repository.load_growspaces({})

    def _apply_options_to_growspaces(self, options: dict[str, Any] | None) -> None:
        """Apply configuration options to loaded growspaces."""
        if not options:
            return

        for growspace in self.repository.get_all_growspaces():
            if growspace.id in options:
                opts = options[growspace.id]
                if isinstance(opts, dict):
                    growspace.environment_config = EnvironmentConfig.from_dict(opts)
                else:
                    growspace.environment_config = opts

    def _load_nutrient_presets(self, data: dict[str, Any]) -> dict[str, NutrientPreset]:
        """Load nutrient presets from storage data."""
        try:
            return {
                pid: NutrientPreset.from_dict(p)
                for pid, p in data.get("nutrient_presets", {}).items()
            }
        except Exception:
            _LOGGER.exception("Error loading nutrient presets")
            return {}

    def _load_ipm_presets(self, data: dict[str, Any]) -> dict[str, IPMPreset]:
        """Load IPM presets from storage data."""
        try:
            return {
                pid: IPMPreset.from_dict(p)
                for pid, p in data.get("ipm_presets", {}).items()
            }
        except Exception:
            _LOGGER.exception("Error loading IPM presets")
            return {}

    def _load_ec_ramp_curves(self, data: dict[str, Any]) -> dict[str, ECRampCurve]:
        """Load EC ramp curves from storage data."""
        try:
            return {
                cid: ECRampCurve.from_dict(c)
                for cid, c in data.get("ec_ramp_curves", {}).items()
            }
        except Exception:
            _LOGGER.exception("Error loading EC ramp curves")
            return {}

    def _load_genetics(self, data: dict[str, Any]) -> None:
        """Load genetics data (seed batches and pollination events)."""
        if self.genetics_manager is None:
            return
        try:
            seed_batches = {
                bid: SeedBatch.from_dict(b)
                for bid, b in data.get("seed_batches", {}).items()
            }
            pollination_events = {
                eid: PollinationEvent.from_dict(e)
                for eid, e in data.get("pollination_events", {}).items()
            }
            self.genetics_manager.load_data(seed_batches, pollination_events)
            _LOGGER.info(
                "Loaded %d seed batches and %d pollination events",
                len(seed_batches),
                len(pollination_events),
            )
        except Exception:
            _LOGGER.exception("Error loading genetics data")

    def _load_nutrient_inventory(self, data: dict[str, Any]) -> NutrientInventory:
        """Load nutrient inventory from storage data."""
        try:
            # Explicitly type the result of from_dict
            inventory: NutrientInventory = NutrientInventory.from_dict(
                data.get("nutrient_inventory", {})
            )
        except Exception:
            _LOGGER.exception("Error loading nutrient inventory")
            return NutrientInventory()
        else:
            return inventory
