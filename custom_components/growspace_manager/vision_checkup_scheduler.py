"""Vision checkup scheduler for AI-powered plant health analysis.

Schedules automated camera snapshots at 3 points during each light cycle
and sends them to an AI vision model for plant health analysis.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from datetime import datetime, time, timedelta
import logging
from pathlib import Path
import shutil
from typing import TYPE_CHECKING, Any, cast

import voluptuous as vol

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util.dt import now as ha_now, utcnow

from .domain.light_schedule import resolve_photoperiod_hours
from .image_processor import GrowspaceImageProcessor
from .models import VisionCheckupResult
from .raw_snapshot_store import RawSnapshotStore

if TYPE_CHECKING:
    from homeassistant.core import CALLBACK_TYPE, HomeAssistant

    from .coordinator import GrowspaceCoordinator
    from .models import Growspace
    from .strain_library import StrainLibrary

_LOGGER = logging.getLogger(__name__)

# Structured-output schema for the AI vision analysis. Passing this as the
# ``structure`` argument to ``async_generate_data`` makes the AI task return a
# parsed dict; without it the result ``.data`` is raw text and the dict access
# in ``run_vision_analysis`` raises ``AttributeError``.
VISION_RESULT_SCHEMA = vol.Schema(
    {
        vol.Required("analysis"): str,
        vol.Required("issues_detected"): [str],
        vol.Required("severity"): vol.In(["none", "low", "medium", "high", "critical"]),
        vol.Required("recommendations"): [str],
    }
)


def calculate_checkup_times(
    lights_on_time: time,
    day_hours: int,
    early_offset_minutes: int = 60,
    mid_check_hours: int = 6,
    late_offset_minutes: int = 60,
) -> dict[str, time]:
    """Calculate the 3 checkup times within a light cycle.

    Args:
        lights_on_time: Time when lights turn on (e.g., 06:00).
        day_hours: Hours of light per day (18 for veg, 12 for flower).
        early_offset_minutes: Minutes after lights on for early check.
        mid_check_hours: Hours into light cycle for mid check.
        late_offset_minutes: Minutes before lights off for late check.

    Returns:
        Dict with "early", "mid", "late" keys mapped to time objects.

    """
    # Use a reference date for time arithmetic that may cross midnight
    ref = datetime(2000, 1, 1, lights_on_time.hour, lights_on_time.minute)

    early_dt = ref + timedelta(minutes=early_offset_minutes)
    mid_dt = ref + timedelta(hours=mid_check_hours)
    late_dt = ref + timedelta(hours=day_hours) - timedelta(minutes=late_offset_minutes)

    return {
        "early": early_dt.time(),
        "mid": mid_dt.time(),
        "late": late_dt.time(),
    }


class VisionCheckupScheduler:
    """Schedules and executes AI vision checkups for growspaces."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: GrowspaceCoordinator,
    ) -> None:
        """Initialize the vision checkup scheduler."""
        self.hass = hass
        self.coordinator = coordinator
        self._unsub_timers: dict[str, list[CALLBACK_TYPE]] = {}
        self._latest_public_paths: dict[str, list[str]] = {}

    def _get_ai_task_entity_id(self) -> str | None:
        """Get the configured AI task entity ID from coordinator options."""
        ai_settings = self.coordinator.options.get("ai_settings", {})
        return cast("str | None", ai_settings.get("ai_task_entity_id"))

    def _get_active_day_hours(self, growspace: Growspace) -> int:
        """Determine active light hours based on dominant plant stage.

        Uses the same ``flower_start``-based resolution as the grow light
        controller (see ``grow_light_coordinator._photoperiod_hours``) rather
        than the cached ``plant.stage`` attribute, which is only set once at
        plant creation and does not update when a plant flips to flower.
        """
        plants = self.coordinator.services.growspaces.get_growspace_plants(growspace.id)
        env = growspace.environment_config
        return int(
            resolve_photoperiod_hours(
                plants, env.veg_day_hours, env.flower_day_hours, ha_now().date()
            )
        )

    def _get_lights_on_time(self, growspace: Growspace) -> time:
        """Parse the lights_on_time from the irrigation strategy."""
        raw = growspace.irrigation_strategy.lights_on_time
        try:
            return datetime.strptime(raw, "%H:%M:%S").time()
        except ValueError:
            return datetime.strptime(raw, "%H:%M").time()

    def _require_strain_library(self) -> StrainLibrary:
        """Return the loaded strain library, raising if it is unavailable."""
        strain_library = self.coordinator.services.config.strain_library
        if strain_library is None:
            raise HomeAssistantError("Strain library is not loaded")
        return strain_library

    def _gather_context_data(self, growspace_id: str) -> dict[str, Any]:
        """Gather growspace context data for the AI prompt."""
        from .services.ai_assistant import GrowAssistant  # noqa: PLC0415

        assistant = GrowAssistant(
            self.hass, self.coordinator, self._require_strain_library()
        )
        return assistant.gather_growspace_data(growspace_id)

    def _build_vision_prompt(
        self,
        growspace_id: str,
        check_type: str,
        context_data: dict[str, Any],
        previous_results: list[VisionCheckupResult],
    ) -> str:
        """Build the vision analysis prompt with full growspace context.

        Interim shape. The evidence-explainer rewrite (ADR 0042) lives in
        ``domain/vision_explainer_prompt.py`` and is wired in by hub#73, once the
        Evidence Fusion Outcome and Visual Comparison Result seams exist. What
        changes here now is only the canopy-coverage claim, which had no such
        dependency: the HSV green-pixel statistic varies 31.5% inside a fixed
        camera's healthy bucket (hub#68), so stating it as a measured fact
        alongside the image invited the model to reason from it.

        The MOISTURE INTERPRETATION RULE below deliberately stays until that
        rewrite lands. Weak as it is, it is the only counterweight currently
        standing between the sensor block and the image; removing it first would
        make contamination worse, not better.
        """
        from .services.ai_assistant import GrowAssistant  # noqa: PLC0415

        assistant = GrowAssistant(
            self.hass, self.coordinator, self._require_strain_library()
        )
        env_context = assistant._format_context_data(context_data)  # noqa: SLF001

        # Build trend context from recent history
        trend_context = ""
        if previous_results:
            trend_lines = ["PREVIOUS CHECKUP HISTORY (newest first):"]
            trend_lines.extend(
                f"  [{prev.timestamp}] {prev.check_type}: severity={prev.severity}, "
                f"issues={', '.join(prev.issues_detected) or 'none'}"
                for prev in previous_results[:5]
            )
            trend_context = "\n".join(trend_lines) + "\n\n"

        check_type_descriptions = {
            "early": "1 hour after lights turned on (checking overnight recovery)",
            "mid": "6 hours into the light cycle (peak transpiration period)",
            "late": "1 hour before lights turn off (end-of-day stress check)",
            "manual": "Manual on-demand checkup",
        }
        timing_desc = check_type_descriptions.get(check_type, check_type)

        return (
            "You are an expert cannabis plant health analyst performing a visual inspection.\n\n"
            f"TIMING: This is a {check_type} checkup ({timing_desc}).\n\n"
            f"{env_context}\n\n"
            f"{trend_context}"
            "GRID REFERENCE: The attached image has a 4x4 grid overlay with sectors labeled "
            "A1–A4 (top row) through D1–D4 (bottom row). When you identify any issue, you MUST "
            "specify the exact grid sector(s) where it is visible (e.g., 'yellowing in B2 and C3'). "
            "This helps the grower locate the problem quickly.\n\n"
            "Analyze the attached camera image(s) from this growspace. Look carefully for:\n"
            "1. **Leaf health**: drooping, curling (up or down), yellowing, browning, spots, necrosis\n"
            "2. **Pest signs**: visible insects, webbing (spider mites), white powder (powdery mildew), "
            "dark spots (fungus gnats damage), leaf miners trails\n"
            "3. **Nutrient issues**: interveinal chlorosis (Mg/Fe), purple stems (P), tip burn (N toxicity or K), "
            "rust spots (Ca/Mg), overall yellowing (N deficiency)\n"
            "4. **Environmental stress**: heat stress (taco leaves), light burn (bleaching), wind burn, "
            "overwatering (droopy + dark leaves), underwatering (droopy + light/dry)\n"
            "5. **Growth patterns**: stretching, foxtailing, hermaphrodite signs (nanners/bananas)\n"
            "6. **General vigor**: canopy uniformity, color consistency, stem thickness\n\n"
            "Compare with the sensor data above when interpreting what you see.\n\n"
            "MOISTURE INTERPRETATION RULE: Use the effective Acceptable Moisture Band stated "
            "above for the sensor reading. An in-band reading alone is not evidence of "
            "overwatering or underwatering. Visible plant symptoms may still justify a "
            "moisture-stress conclusion even while the sensor reading is within that band; "
            "name the visible evidence when doing so.\n\n"
            "Return your analysis as structured data with these fields:\n"
            "- analysis: A concise paragraph describing what you see, referencing grid sectors for any issues\n"
            "- issues_detected: A list of issue keywords (e.g., leaf_drooping, nitrogen_deficiency). "
            "Use empty list if no issues.\n"
            "- severity: One of 'none', 'low', 'medium', 'high', 'critical'\n"
            "- recommendations: A list of specific, actionable recommendations. Use empty list if no action needed.\n"
        )

    async def _process_camera_images(
        self,
        growspace_id: str,
        camera_entities: list[str],
    ) -> tuple[list[dict[str, str]], float | None, list[Path]]:
        """Fetch, process, and save camera snapshots for vision analysis.

        Fetches a live image from each camera entity, runs the image processor
        (green-pixel coverage + 4x4 grid overlay) in a thread, then writes the
        result to ``config/media/growspace_vision/`` so it can be referenced via
        a ``media-source://media_source/local/`` URI in the AI task attachment.

        Args:
            growspace_id: Used to namespace the saved filenames.
            camera_entities: List of camera entity IDs to capture.

        Returns:
            Tuple of:
            - attachment dicts ready for ``async_generate_data``
            - average canopy coverage across all processed cameras (or None)
            - list of Path objects for saved files (for cleanup after the AI call)

        """
        from homeassistant.components.camera import async_get_image  # noqa: PLC0415

        self._latest_public_paths[growspace_id] = []
        processor = GrowspaceImageProcessor()
        timestamp = utcnow().strftime("%Y%m%d_%H%M%S")

        # The attachment URI below resolves via the local media source, whose
        # on-disk root is hass.config.media_dirs[source_dir_id] — NOT
        # config.path("media"). In a Docker/HA-OS install those differ
        # (/media vs <config>/media), so we must write where the media source
        # will look, or the AI task fails with "<path> does not exist".
        media_dirs = self.hass.config.media_dirs
        source_dir_id = (
            "local" if "local" in media_dirs else next(iter(media_dirs), None)
        )
        if source_dir_id is None:
            _LOGGER.warning(
                "No media directories configured; cannot save vision snapshots"
            )
            return [], None, []

        media_dir = Path(media_dirs[source_dir_id]) / "growspace_vision"
        try:
            await self.hass.async_add_executor_job(
                lambda: media_dir.mkdir(parents=True, exist_ok=True)
            )
        except OSError:
            _LOGGER.exception(
                "Failed to create media directory %s, skipping image processing",
                media_dir,
            )
            return [], None, []

        snapshot_dir = (
            Path(self.hass.config.path("www"))
            / "growspace_manager"
            / "snapshots"
            / growspace_id
        )
        try:
            await self.hass.async_add_executor_job(
                lambda: snapshot_dir.mkdir(parents=True, exist_ok=True)
            )
        except OSError:
            _LOGGER.exception(
                "Failed to create snapshots directory %s, permanent copies will not be saved",
                snapshot_dir,
            )

        attachments: list[dict[str, str]] = []
        coverages: list[float] = []
        temp_paths: list[Path] = []
        raw_store = RawSnapshotStore(media_dir / "raw")

        for i, cam_entity in enumerate(camera_entities):
            try:
                image = await async_get_image(self.hass, cam_entity)
            except Exception:  # noqa: BLE001
                _LOGGER.warning(
                    "Failed to fetch snapshot from camera %s, skipping", cam_entity
                )
                continue

            captured_at = ha_now()
            capture_timestamp = captured_at.strftime("%Y%m%d_%H%M%S_%f")
            safe_name = cam_entity.replace(".", "_").replace(" ", "_")
            capture_stem = f"{capture_timestamp}_{safe_name}"

            try:
                await self.hass.async_add_executor_job(
                    raw_store.save,
                    growspace_id,
                    capture_stem,
                    image.content,
                    getattr(image, "content_type", None),
                    captured_at,
                )
            except OSError:
                _LOGGER.exception(
                    "Failed to save raw snapshot bytes for %s", cam_entity
                )

            try:
                processed_bytes, coverage = await self.hass.async_add_executor_job(
                    processor.process_snapshot, image.content
                )
            except Exception:  # noqa: BLE001
                _LOGGER.warning(
                    "Image processing failed for camera %s, skipping", cam_entity
                )
                continue

            filename = f"{growspace_id}_{timestamp}_{i}.jpg"
            file_path = media_dir / filename

            try:
                await self.hass.async_add_executor_job(
                    file_path.write_bytes, processed_bytes
                )
            except OSError:
                _LOGGER.exception("Failed to save processed image to %s", file_path)
                continue

            temp_paths.append(file_path)

            # Save a permanent copy to the www snapshots directory
            try:
                snapshot_filename = f"{capture_stem}_processed.jpg"
                snapshot_file_path = snapshot_dir / snapshot_filename

                await self.hass.async_add_executor_job(
                    snapshot_file_path.write_bytes, processed_bytes
                )

                public_path = f"/local/growspace_manager/snapshots/{growspace_id}/{snapshot_filename}"
                self._latest_public_paths[growspace_id].append(public_path)
            except Exception:
                _LOGGER.exception(
                    "Failed to save processed snapshot copy for %s", cam_entity
                )

            attachments.append(
                {
                    "media_content_id": (
                        f"media-source://media_source/{source_dir_id}"
                        f"/growspace_vision/{filename}"
                    )
                }
            )
            coverages.append(coverage)
            _LOGGER.debug(
                "Processed camera %s: coverage=%.1f%%, saved to %s",
                cam_entity,
                coverage,
                file_path,
            )

        avg_coverage = round(sum(coverages) / len(coverages), 1) if coverages else None
        return attachments, avg_coverage, temp_paths

    def _cancel_growspace_timers(self, growspace_id: str) -> None:
        """Cancel all scheduled timers for a specific growspace."""
        for unsub in self._unsub_timers.pop(growspace_id, []):
            unsub()

    def async_stop(self) -> None:
        """Cancel all scheduled timers for all growspaces."""
        for growspace_id in list(self._unsub_timers):
            self._cancel_growspace_timers(growspace_id)

    def schedule_growspace(self, growspace_id: str) -> None:
        """Schedule vision checkups for a specific growspace.

        Calculates the next occurrence of each checkup time today (or tomorrow
        if the time has already passed) and registers a one-shot timer for each.
        After each check fires, the callback reschedules for the next day.
        """
        self._cancel_growspace_timers(growspace_id)

        growspace = self.coordinator.growspaces.get(growspace_id)
        if not growspace:
            return

        vision_config = growspace.environment_config.vision_checkup_config
        if not vision_config.enabled:
            _LOGGER.debug("Vision checkup disabled for growspace %s", growspace_id)
            return

        if not growspace.environment_config.camera_entities:
            _LOGGER.debug(
                "No cameras configured for %s, skipping vision scheduling", growspace_id
            )
            return

        lights_on = self._get_lights_on_time(growspace)
        day_hours = self._get_active_day_hours(growspace)

        checkup_times = calculate_checkup_times(
            lights_on_time=lights_on,
            day_hours=day_hours,
            early_offset_minutes=vision_config.early_check_offset_minutes,
            mid_check_hours=vision_config.mid_check_hours,
            late_offset_minutes=vision_config.late_check_offset_minutes,
        )

        current = ha_now()
        unsubs: list[CALLBACK_TYPE] = []

        for check_type, check_time in checkup_times.items():
            next_run = current.replace(
                hour=check_time.hour,
                minute=check_time.minute,
                second=0,
                microsecond=0,
            )
            if next_run <= current:
                next_run += timedelta(days=1)

            _LOGGER.debug(
                "Scheduling %s vision checkup for %s at %s",
                check_type,
                growspace_id,
                next_run.isoformat(),
            )

            unsub = async_track_point_in_utc_time(
                self.hass,
                self._create_checkup_callback(growspace_id, check_type),
                next_run,
            )
            unsubs.append(unsub)

        self._unsub_timers[growspace_id] = unsubs

    def schedule_all_growspaces(self) -> None:
        """Schedule vision checkups for all growspaces."""
        for growspace_id in self.coordinator.growspaces:
            self.schedule_growspace(growspace_id)

    def _create_checkup_callback(
        self, growspace_id: str, check_type: str
    ) -> Callable[[datetime], Coroutine[Any, Any, None]]:
        """Create a callback for a scheduled checkup that reschedules after running."""

        async def _callback(_now: datetime) -> None:
            """Execute vision checkup and reschedule for next day."""
            _LOGGER.info(
                "Running scheduled %s vision checkup for %s",
                check_type,
                growspace_id,
            )
            try:
                result = await self.run_vision_analysis(growspace_id, check_type)
                if result and result.severity in ("high", "critical"):
                    await self._send_vision_notification(growspace_id, result)
            except Exception:
                _LOGGER.exception(
                    "Error during scheduled %s vision checkup for %s",
                    check_type,
                    growspace_id,
                )
            # Reschedule for the next day (one-shot timers need re-registration)
            self.schedule_growspace(growspace_id)

        return _callback

    async def _send_vision_notification(
        self, growspace_id: str, result: VisionCheckupResult
    ) -> None:
        """Send a notification when vision analysis detects high/critical issues."""
        growspace = self.coordinator.growspaces.get(growspace_id)
        if not growspace or not growspace.notification_target:
            return

        issues_str = (
            ", ".join(result.issues_detected) if result.issues_detected else "unknown"
        )
        recommendations_str = "\n".join(f"- {r}" for r in result.recommendations[:3])

        message = (
            f"Vision checkup ({result.check_type}) for {growspace.name}:\n"
            f"Severity: {result.severity}\n"
            f"Issues: {issues_str}\n"
            f"Recommendations:\n{recommendations_str}"
        )

        try:
            await self.hass.services.async_call(
                "notify",
                growspace.notification_target.replace("notify.", ""),
                {"message": message, "title": f"Vision Alert: {growspace.name}"},
            )
        except Exception:
            _LOGGER.exception(
                "Failed to send vision notification for growspace %s", growspace_id
            )

    async def run_vision_analysis(
        self,
        growspace_id: str,
        check_type: str,
    ) -> VisionCheckupResult | None:
        """Run a vision analysis for a growspace.

        Args:
            growspace_id: ID of the growspace to analyze.
            check_type: Type of check ("early", "mid", "late", "manual").

        Returns:
            VisionCheckupResult or None if skipped (no cameras, AI error, etc.).
        """
        from homeassistant.components import ai_task  # noqa: PLC0415

        growspace = self.coordinator.growspaces.get(growspace_id)
        if not growspace:
            _LOGGER.warning("Growspace %s not found for vision checkup", growspace_id)
            raise ServiceValidationError(f"Growspace '{growspace_id}' not found")

        camera_entities = growspace.environment_config.camera_entities
        if not camera_entities:
            _LOGGER.debug(
                "No cameras configured for %s, skipping vision checkup", growspace_id
            )
            raise ServiceValidationError(
                "No cameras configured for this growspace. Please add cameras in the environment settings."
            )

        entity_id = self._get_ai_task_entity_id()
        if not entity_id:
            raise ServiceValidationError(
                "No AI task entity configured. Please set up an AI agent in the integration options."
            )

        # Gather growspace context for the AI prompt
        try:
            context_data = self._gather_context_data(growspace_id)
        except Exception:
            _LOGGER.exception("Failed to gather context data for %s", growspace_id)
            context_data = {
                "growspace": {
                    "id": growspace_id,
                    "name": growspace.name,
                    "size": "unknown",
                    "total_plants": 0,
                },
                "environment": {"sensors": {}},
                "analysis": {
                    "stress": {"active": False, "reasons": []},
                    "mold_risk": {"active": False, "reasons": []},
                    "optimal": {"active": False, "reasons": []},
                    "light_schedule": {"correct": True},
                },
                "plants": {
                    "count": 0,
                    "stages": {},
                    "strains": [],
                    "max_veg_days": 0,
                    "max_flower_days": 0,
                },
                "strain_analytics": {},
            }

        # Process camera images: apply green-coverage analysis and grid overlay.
        # Falls back to direct camera URIs if processing fails for all cameras.
        attachments, _coverage, temp_paths = await self._process_camera_images(
            growspace_id, camera_entities
        )
        if not attachments:
            _LOGGER.warning(
                "Image processing yielded no results for %s; using raw camera URIs",
                growspace_id,
            )
            attachments = [
                {"media_content_id": f"media-source://camera/{cam}"}
                for cam in camera_entities
            ]

        prompt = self._build_vision_prompt(
            growspace_id,
            check_type,
            context_data,
            growspace.vision_checkup_history,
        )

        try:
            task_result = await ai_task.async_generate_data(
                self.hass,
                task_name="growspace_vision_checkup",
                entity_id=entity_id,
                instructions=prompt,
                structure=VISION_RESULT_SCHEMA,
                attachments=attachments,
            )
        except Exception as err:
            _LOGGER.exception(
                "AI vision analysis failed for growspace %s", growspace_id
            )
            raise HomeAssistantError(f"AI vision analysis failed: {err}") from err
        finally:
            ai_settings = self.coordinator.options.get("ai_settings", {})
            debug_enabled = ai_settings.get("vision_debug_enabled", False)
            if debug_enabled and temp_paths:
                debug_dir = Path(self.hass.config.path("openCVDebug"))
                try:
                    await self.hass.async_add_executor_job(
                        lambda: debug_dir.mkdir(parents=True, exist_ok=True)
                    )
                    for path in temp_paths:
                        debug_path = debug_dir / path.name
                        await self.hass.async_add_executor_job(
                            shutil.copy2, path, debug_path
                        )
                except Exception:
                    _LOGGER.exception("Failed to save openCVDebug images")

            for path in temp_paths:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    _LOGGER.debug("Could not remove temp vision file %s", path)

        data = task_result.data or {}

        public_paths = self._latest_public_paths.pop(growspace_id, [])
        if not public_paths:
            public_paths = [f"media-source://camera/{c}" for c in camera_entities]

        result = VisionCheckupResult(
            timestamp=utcnow().isoformat(),
            growspace_id=growspace_id,
            check_type=check_type,
            snapshot_paths=public_paths,
            analysis=data.get("analysis", "Analysis unavailable"),
            issues_detected=data.get("issues_detected", []),
            severity=data.get("severity", "none"),
            recommendations=data.get("recommendations", []),
        )

        history_limit = growspace.environment_config.vision_checkup_config.history_limit
        growspace.vision_checkup_history.insert(0, result)
        growspace.vision_checkup_history = growspace.vision_checkup_history[
            :history_limit
        ]

        await self.coordinator.async_commit()

        _LOGGER.info(
            "Vision checkup completed for %s: severity=%s, issues=%s",
            growspace_id,
            result.severity,
            result.issues_detected,
        )

        return result
