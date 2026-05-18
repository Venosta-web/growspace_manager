"""Import/Export management for the Strain Library."""

from __future__ import annotations

import json
import logging
from pathlib import Path
import shutil
from typing import Any, cast
import zipfile

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)


class ImportExportManager:
    """Manages import and export of strain library data."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the ImportExportManager.

        Args:
            hass: Home Assistant instance.
        """
        self.hass = hass

    async def export_library(
        self, library_data: dict[str, Any], output_dir: str
    ) -> str:
        """Export the library data and images to a ZIP file.

        Args:
            library_data: The dictionary containing all strain data.
            output_dir: The directory to save the ZIP file.

        Returns:
            The path to the created ZIP file.
        """
        return cast(
            str,
            await self.hass.async_add_executor_job(
                self._export_sync, library_data, output_dir
            ),
        )

    def _export_sync(self, library_data: dict[str, Any], output_dir: str) -> str:
        """Synchronous helper to create the export ZIP file."""
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        timestamp = dt_util.now().strftime("%Y%m%d_%H%M%S")
        zip_path = out_path / f"strain_library_export_{timestamp}.zip"

        # Create a deep copy or modify a copy to avoid changing the original data
        # We need to adjust image paths for the zip
        export_data = json.loads(json.dumps(library_data))

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for strain_data in export_data.values():
                if "phenotypes" in strain_data:
                    for pheno_data in strain_data["phenotypes"].values():
                        if "image_path" in pheno_data:
                            img_path = pheno_data["image_path"]
                            if img_path and img_path.startswith("/local/"):
                                rel = img_path.replace("/local/", "", 1)
                                fs_path = Path(self.hass.config.path("www", rel))
                                if fs_path.exists():
                                    zip_name = f"images/{fs_path.name}"
                                    zipf.write(fs_path, zip_name)
                                    pheno_data["image_path"] = zip_name

            zipf.writestr("library.json", json.dumps(export_data, indent=2))

        _LOGGER.info("Exported strain library to %s", zip_path)
        return str(zip_path)

    async def import_library(
        self, zip_path: str, target_image_dir: str
    ) -> dict[str, Any]:
        """Import a library from a ZIP archive.

        Args:
            zip_path: Path to the ZIP file.
            target_image_dir: Directory to extract images to.

        Returns:
            The imported library data dictionary.
        """
        return cast(
            dict[str, Any],
            await self.hass.async_add_executor_job(
                self._import_sync, zip_path, target_image_dir
            ),
        )

    def _import_sync(self, zip_path: str, target_image_dir: str) -> dict[str, Any]:
        """Synchronous helper to import from a ZIP file."""
        zip_file = Path(zip_path)
        if not zip_file.exists():
            raise FileNotFoundError(f"ZIP file not found: {zip_path}")
        if not zipfile.is_zipfile(zip_path):
            raise ValueError(f"Not a valid ZIP file: {zip_path}")

        target_path = Path(target_image_dir)
        target_path.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(zip_path, "r") as zipf:
            if "library.json" not in zipf.namelist():
                raise ValueError("library.json missing from archive")

            with zipf.open("library.json") as f:
                library_data = json.load(f)

            for info in zipf.infolist():
                if info.filename.startswith("images/") and not info.is_dir():
                    # Extract image
                    dest = target_path / Path(info.filename).name
                    with zipf.open(info) as src, dest.open("wb") as dst:
                        shutil.copyfileobj(src, dst)

        return cast(dict[str, Any], library_data)
