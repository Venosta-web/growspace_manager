"""Builder for constructing GrowspaceCoordinator with all dependencies."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .alert_monitor import AlertMonitor
from .briefing_scheduler import BriefingScheduler
from .cache import CacheManager
from .conversation_store import ConversationStore
from .data_access.growspace_repository import GrowspaceRepository
from .data_access.notification_state import NotificationState
from .date_time_helper import DateTimeHelper
from .environment_analyzer import EnvironmentAnalyzer
from .event_bus_pkg import GrowspaceEventBus
from .growspace_validator import GrowspaceValidator
from .import_export_manager import ImportExportManager
from .managers.genetics import GeneticsManager
from .managers.growspace import GrowspaceManager
from .managers.nutrient import NutrientManager
from .managers.plant import PlantManager
from .managers.subsystem import SubsystemManager
from .notification_manager import NotificationManager
from .notification_rewriter import AINotificationRewriter
from .notifications import NotificationSettingsManager
from .photoperiod_flip_checker import PhotoperiodFlipChecker
from .presentation import PlantViewModelBuilder
from .services.context import ServiceContext
from .services.environment_reporter import EnvironmentReporter
from .services.facade import ServiceFacade
from .services.ipm_service import IPMService
from .services.seedfinder_scraper import SeedfinderScraper
from .services.training_service import TrainingService
from .services.watering_service import WateringService
from .storage_manager import StorageManager
from .strain_library import StrainLibrary
from .view_model_builder import ViewModelBuilder
from .vision_checkup_scheduler import VisionCheckupScheduler

_LOGGER = logging.getLogger(__name__)


class CoordinatorBuilder:
    """Constructs a fully wired GrowspaceCoordinator.

    The coordinator's __init__ accepts only pre-built pure dependencies.
    This builder owns all construction logic, keeping __init__ as a thin
    holder and making each collaborator injectable for tests.

    Usage::

        coordinator = CoordinatorBuilder(hass, entry).build(data=data, options=options)
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
    ) -> None:
        """Initialise the builder with the HA instance and config entry."""
        self.hass = hass
        self.entry = entry

    def build(
        self,
        data: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
        strain_library: StrainLibrary | None = None,
        seedfinder_scraper: SeedfinderScraper | None = None,
    ) -> Any:
        """Build a fully configured GrowspaceCoordinator.

        Args:
            data: Raw storage data to restore. If None, starts fresh.
            options: Config entry options.
            strain_library: Pre-initialised library; creates one if omitted.
            seedfinder_scraper: Pre-initialised scraper; creates one if omitted.

        Returns:
            Fully initialised GrowspaceCoordinator ready for async_load().
        """
        from .coordinator import GrowspaceCoordinator  # noqa: PLC0415

        _LOGGER.debug(
            "Building GrowspaceCoordinator for entry %s",
            self.entry.entry_id,
        )

        # ------------------------------------------------------------------
        # Phase 1 – pure collaborators (no coordinator reference needed)
        # ------------------------------------------------------------------
        alert_store = Store(self.hass, 1, "growspace_manager.ai_alerts")
        conversation_store = ConversationStore(
            Store(self.hass, 1, "growspace_manager.ai_conversations")
        )
        repository = GrowspaceRepository()
        notification_state = NotificationState()
        lock = asyncio.Lock()
        cache = CacheManager()
        date_time_helper = DateTimeHelper()
        event_bus = GrowspaceEventBus(self.hass)
        plant_view_builder = PlantViewModelBuilder(self.hass)
        import_export_manager = ImportExportManager(self.hass)

        if strain_library is None:
            strain_library = StrainLibrary(self.hass)
        if seedfinder_scraper is None:
            seedfinder_scraper = SeedfinderScraper(self.hass)

        validator = GrowspaceValidator(repository)

        # ------------------------------------------------------------------
        # Phase 2 – coordinator shell (thin __init__, no construction)
        # ------------------------------------------------------------------
        coordinator = GrowspaceCoordinator(
            self.hass,
            self.entry,
            data_repository=repository,
            notification_state=notification_state,
            lock=lock,
            cache=cache,
            date_time_helper=date_time_helper,
            event_bus=event_bus,
            strain_library=strain_library,
            seedfinder_scraper=seedfinder_scraper,
            plant_view_builder=plant_view_builder,
            import_export_manager=import_export_manager,
            validator=validator,
            options=options,
        )

        # Load initial data now that repo + notification_state are stored on the
        # coordinator. Managers are not yet attached, so no callbacks fire here.
        if data:
            coordinator._load_initial_data(data)  # noqa: SLF001

        # ------------------------------------------------------------------
        # Phase 3 – coordinator-callback-dependent collaborators
        # (_save_callback and add_event are bound methods; safe to reference
        # now that the coordinator shell exists, even before _attach_services)
        # ------------------------------------------------------------------
        view_model_builder = ViewModelBuilder(coordinator)

        nutrient_manager = NutrientManager(repository, coordinator._save_callback)  # noqa: SLF001
        genetics_manager = GeneticsManager(
            repository,
            coordinator._save_callback,  # noqa: SLF001
            strain_library=strain_library,
        )
        storage_manager = StorageManager(
            self.hass,
            repository,
            nutrient_manager,
            genetics_manager,
            notification_state,
        )

        svc_ctx = ServiceContext(
            save_callback=coordinator._save_callback,  # noqa: SLF001
            lock=lock,
            add_event=coordinator.add_event,
            invalidate_cache=cache.invalidate,
        )

        growspace_manager = GrowspaceManager(
            svc_ctx,
            self.hass,
            repository,
            notification_state,
            validator,
            view_model_builder,
        )
        plant_manager = PlantManager(
            svc_ctx,
            self.hass,
            repository,
            notification_state,
            validator,
            growspace_manager,
            strain_library,
            plant_view_builder,
        )
        watering_service = WateringService(
            svc_ctx,
            self.hass,
            repository,
            validator,
            nutrient_manager,
        )
        training_service = TrainingService(svc_ctx, self.hass, repository)
        ipm_service = IPMService(svc_ctx, self.hass, repository)

        environment_analyzer = EnvironmentAnalyzer(self.hass, coordinator)
        environment_reporter = EnvironmentReporter(self.hass, coordinator)
        ai_rewriter = AINotificationRewriter(self.hass)
        notification_manager = NotificationManager(self.hass, coordinator, ai_rewriter)
        notification_settings = NotificationSettingsManager(coordinator)
        subsystem_manager = SubsystemManager(self.hass, coordinator, self.entry)
        services = ServiceFacade(coordinator)
        vision_scheduler = VisionCheckupScheduler(self.hass, coordinator)
        briefing_scheduler = BriefingScheduler(self.hass, coordinator)
        photoperiod_checker = PhotoperiodFlipChecker(self.hass, coordinator)

        from .services.ai_assistant import GrowAssistant  # noqa: PLC0415

        def _make_ai_assistant() -> GrowAssistant:
            return GrowAssistant(self.hass, coordinator, strain_library)

        alert_monitor = AlertMonitor(
            self.hass,
            coordinator=coordinator,
            store=alert_store,
            ai_assistant_factory=_make_ai_assistant,
        )

        # ------------------------------------------------------------------
        # Phase 4 – attach all services to the coordinator
        # ------------------------------------------------------------------
        coordinator._attach_services(  # noqa: SLF001
            view_model_builder=view_model_builder,
            nutrient_manager=nutrient_manager,
            genetics_manager=genetics_manager,
            storage_manager=storage_manager,
            growspace_manager=growspace_manager,
            plant_manager=plant_manager,
            watering_service=watering_service,
            training_service=training_service,
            ipm_service=ipm_service,
            environment_analyzer=environment_analyzer,
            environment_reporter=environment_reporter,
            notification_manager=notification_manager,
            notification_settings=notification_settings,
            subsystem_manager=subsystem_manager,
            services=services,
            vision_scheduler=vision_scheduler,
            briefing_scheduler=briefing_scheduler,
            photoperiod_checker=photoperiod_checker,
            alert_monitor=alert_monitor,
            conversation_store=conversation_store,
        )

        _LOGGER.debug("GrowspaceCoordinator built successfully")
        return coordinator
