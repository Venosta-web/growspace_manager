"""Image management for the Strain Library."""

from __future__ import annotations

import base64
import logging
from io import BytesIO
from pathlib import Path

from homeassistant.core import HomeAssistant
from PIL import Image

_LOGGER = logging.getLogger(__name__)


class ImageManager:
    """Manages image processing and storage for the Strain Library."""

    def __init__(self, hass: HomeAssistant, storage_dir: str) -> None:
        """Initialize the ImageManager.

        Args:
            hass: Home Assistant instance.
            storage_dir: Directory to store images.
        """
        self.hass = hass
        self.storage_dir = Path(storage_dir)
        self._image_cache: set[str] = set()
        self._ensure_storage_dir()
        self._build_cache()

    def _ensure_storage_dir(self) -> None:
        """Ensure the storage directory exists."""
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _build_cache(self) -> None:
        """Populate the image cache from disk."""
        try:
            if self.storage_dir.exists():
                self._image_cache = {f.name for f in self.storage_dir.glob("*.jpg")}
        except OSError as e:
            _LOGGER.error("Error building image cache: %s", e)

    async def save_strain_image(
        self, strain_id: str, phenotype_id: str | None, image_base64: str
    ) -> str:
        """Decode and save a strain image to the storage directory.

        Args:
            strain_id: The ID of the strain.
            phenotype_id: The ID of the phenotype (optional).
            image_base64: The base64 encoded image string.

        Returns:
            The local path to the saved image.
        """
        return await self.hass.async_add_executor_job(
            self._save_image_sync, strain_id, phenotype_id, image_base64
        )

    def _save_image_sync(
        self, strain_id: str, phenotype_id: str | None, image_base64: str
    ) -> str:
        """Synchronous helper to save the image."""
        try:
            # Remove header if present
            if "," in image_base64:
                image_base64 = image_base64.split(",")[1]

            image_data = base64.b64decode(image_base64)
            image = Image.open(BytesIO(image_data))

            # Convert to RGB if necessary
            if image.mode != "RGB":
                image = image.convert("RGB")

            # Generate filename
            filename = f"{strain_id}"
            if phenotype_id:
                filename += f"_{phenotype_id}"
            filename += ".jpg"

            file_path = self.storage_dir / filename

            # Save optimized JPEG
            image.save(file_path, "JPEG", quality=85, optimize=True)

            # Update cache
            self._image_cache.add(filename)

            # Return absolute path as string
            return str(file_path.absolute())

        except Exception as e:
            _LOGGER.error("Error saving strain image: %s", e)
            raise

    def get_image_path(self, strain_id: str, phenotype_id: str | None) -> str | None:
        """Get the path to an existing image using the cache."""
        filename = f"{strain_id}"
        if phenotype_id:
            filename += f"_{phenotype_id}"
        filename += ".jpg"

        if filename in self._image_cache:
            return str((self.storage_dir / filename).absolute())
        return None

    def delete_image(self, strain_id: str, phenotype_id: str | None) -> None:
        """Delete an image if it exists."""
        # Cleanly resolve path manually to avoid double conversion
        filename = f"{strain_id}"
        if phenotype_id:
            filename += f"_{phenotype_id}"
        filename += ".jpg"

        if filename not in self._image_cache:
            return

        file_path = self.storage_dir / filename

        try:
            if file_path.exists():
                file_path.unlink()
            # Update cache regardless of whether file existed on disk to keep sync
            self._image_cache.discard(filename)
        except OSError as e:
            _LOGGER.error("Error deleting image %s: %s", file_path, e)
