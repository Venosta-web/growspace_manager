"""Data models for the Growspace Manager integration.

This file defines the dataclasses that represent the core objects used throughout
the integration, such as Growspace, Plant, and EnvironmentState. These models
provide a structured way to handle and pass around data.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from typing import Any


@dataclass
class Growspace:
    """Represents a single growspace area.

    Attributes:
        id: A unique identifier for the growspace.
        name: The display name of the growspace.
        rows: The number of rows in the growspace grid.
        plants_per_row: The number of plants per row in the grid.
        notification_target: The notification service to use for this growspace.
        created_at: The ISO-formatted date when the growspace was created.
        device_id: The Home Assistant device ID associated with this growspace.
        environment_config: A dictionary of environment sensor configurations.
    """

    id: str
    name: str
    rows: int = 3
    plants_per_row: int = 3
    notification_target: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    device_id: str | None = None
    environment_config: dict[str, Any] = field(default_factory=dict)
    irrigation_config: dict[str, Any] = field(default_factory=dict)
    dehumidifier_config: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert the dataclass instance to a dictionary.

        Returns:
            A dictionary representation of the Growspace.
        """
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> Growspace:
        """Create a Growspace instance from a dictionary.

        This factory method handles the migration of legacy field names
        and filters out any keys that do not correspond to dataclass fields,
        making it robust against data from older versions.

        Args:
            data: A dictionary containing the growspace data.

        Returns:
            A new instance of the Growspace class.
        """
        data = data.copy()  # Don't modify original

        # Migrate old field names
        if "created" in data and "created_at" not in data:
            data["created_at"] = data.pop("created")

        if "updated" in data and "updated_at" not in data:
            data["updated_at"] = data.pop("updated")

        # Only keep keys that match dataclass fields
        allowed_keys = {f.name for f in fields(Growspace)}
        filtered_data = {k: v for k, v in data.items() if k in allowed_keys}

        return Growspace(**filtered_data)


@dataclass
class Plant:
    """Represents a single plant.

    Attributes:
        plant_id: A unique identifier for the plant.
        growspace_id: The ID of the growspace this plant belongs to.
        strain: The strain name of the plant.
        phenotype: The phenotype of the strain.
        row: The row position of the plant in the growspace grid.
        col: The column position of the plant in the growspace grid.
        stage: The current growth stage of the plant.
        type: The type of plant (e.g., 'normal', 'clone', 'mother').
        device_id: The Home Assistant device ID associated with the plant.
        seedling_start: The ISO-formatted date the seedling stage started.
        mother_start: The ISO-formatted date the mother stage started.
        clone_start: The ISO-formatted date the clone stage started.
        veg_start: The ISO-formatted date the vegetative stage started.
        flower_start: The ISO-formatted date the flowering stage started.
        dry_start: The ISO-formatted date the drying stage started.
        cure_start: The ISO-formatted date the curing stage started.
        created_at: The ISO-formatted date the plant was created.
        updated_at: The ISO-formatted date the plant was last updated.
        transition_date: The date of the last stage transition.
        source_mother: The ID of the mother plant this plant was cloned from.
    """

    plant_id: str
    growspace_id: str
    strain: str
    phenotype: str = ""
    row: int = 1
    col: int = 1
    stage: str = ""
    type: str = "normal"
    device_id: str | None = None
    seedling_start: str | None = None
    mother_start: str | None = None
    clone_start: str | None = None
    veg_start: str | None = None
    flower_start: str | None = None
    dry_start: str | None = None
    cure_start: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    transition_date: str | None = None
    source_mother: str | None = None

    def to_dict(self) -> dict:
        """Convert the dataclass instance to a dictionary.

        Returns:
            A dictionary representation of the Plant.
        """
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> Plant:
        """Create a Plant instance from a dictionary.

        This factory method handles the migration of legacy field names
        and filters out any keys that do not correspond to dataclass fields,
        making it robust against data from older versions.

        Args:
            data: A dictionary containing the plant data.

        Returns:
            A new instance of the Plant class.
        """
        data = data.copy()  # Don't modify original

        # Migrate old field names
        if "created" in data and "created_at" not in data:
            data["created_at"] = data.pop("created")

        if "updated" in data and "updated_at" not in data:
            data["updated_at"] = data.pop("updated")

        # Only keep keys that match dataclass fields
        allowed_keys = {f.name for f in fields(Plant)}
        filtered_data = {k: v for k, v in data.items() if k in allowed_keys}

        return Plant(**filtered_data)


@dataclass
class EnvironmentState:
    """Represents a snapshot of the current environment state in a growspace.

    This dataclass is used to pass around a consistent set of environmental
    readings for use in calculations, particularly for the Bayesian sensors.

    Attributes:
        temp: The current temperature.
        humidity: The current relative humidity.
        vpd: The current Vapor Pressure Deficit.
        co2: The current CO2 level.
        veg_days: The number of days the growspace has been in the vegetative stage.
        flower_days: The number of days the growspace has been in the flowering stage.
        is_lights_on: A boolean indicating if the lights are currently on.
        fan_off: A boolean indicating if the circulation fan is currently off.
    """

    temp: float | None
    humidity: float | None
    vpd: float | None
    co2: float | None
    veg_days: int
    flower_days: int
    is_lights_on: bool | None
    fan_off: bool | None
    dehumidifier_on: bool | None = None
    exhaust_value: float | None = None

    humidifier_value: float | None = None
    soil_moisture: float | None = None


@dataclass
class GrowspaceEvent:
    """Represents a historical significant event in a growspace.

    Attributes:
        sensor_type: The type of sensor or source (e.g., 'mold_risk', 'irrigation').
        growspace_id: The ID of the growspace where the event occurred.
        start_time: The ISO-formatted start time of the event.
        end_time: The ISO-formatted end time of the event.
        duration_sec: The duration of the event in seconds.
        severity: The severity or intensity of the event (0.0 to 1.0).
        category: The category of the event (e.g., 'alert', 'irrigation').
        reasons: A list of contributing factors or details.
    """

    sensor_type: str
    growspace_id: str
    start_time: str
    end_time: str
    duration_sec: int
    severity: float
    category: str
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert the dataclass instance to a dictionary."""
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> GrowspaceEvent:
        """Create a GrowspaceEvent instance from a dictionary."""
        data = data.copy()

        # Backward compatibility for 'max_probability'
        if "max_probability" in data and "severity" not in data:
            data["severity"] = data.pop("max_probability")

        # Default category if missing
        if "category" not in data:
            data["category"] = "alert"  # Default for legacy events

        return GrowspaceEvent(**data)
