"""Fail early when the HA test harness and CI Home Assistant pins disagree."""

from __future__ import annotations

import argparse
from importlib import metadata
from pathlib import Path
import re


def exact_pin(requirements: list[str], package: str) -> str:
    """Read one exact package pin from requirement or metadata lines."""
    pattern = re.compile(rf"^{re.escape(package)}\s*==\s*([^\s;#]+)", re.IGNORECASE)
    pins = [
        match.group(1)
        for line in requirements
        if (match := pattern.match(line.strip()))
    ]
    if len(pins) != 1:
        raise ValueError(f"Expected exactly one {package}== pin; found {len(pins)}")
    return pins[0]


def check(requirements_path: Path) -> None:
    """Compare the requested HA release with the installed harness metadata."""
    requirements = requirements_path.read_text(encoding="utf-8").splitlines()
    ha_pin = exact_pin(requirements, "homeassistant")
    plugin_pin = exact_pin(requirements, "pytest-homeassistant-custom-component")
    installed_plugin = metadata.version("pytest-homeassistant-custom-component")
    if installed_plugin != plugin_pin:
        raise ValueError(
            f"Install pytest-homeassistant-custom-component=={plugin_pin} before the check "
            f"(found {installed_plugin})."
        )
    plugin_ha_pin = exact_pin(
        metadata.requires("pytest-homeassistant-custom-component") or [],
        "homeassistant",
    )
    if ha_pin != plugin_ha_pin:
        raise ValueError(
            "Home Assistant test stack pin mismatch: "
            f"requirements.txt has homeassistant=={ha_pin}, but "
            f"pytest-homeassistant-custom-component=={plugin_pin} requires "
            f"homeassistant=={plugin_ha_pin}. Update the pins as a compatible pair; "
            "if the plugin release lags Home Assistant, wait for it to catch up."
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "requirements", nargs="?", type=Path, default=Path("requirements.txt")
    )
    args = parser.parse_args()
    try:
        check(args.requirements)
    except (ValueError, metadata.PackageNotFoundError) as error:
        parser.exit(1, f"{error}\n")
