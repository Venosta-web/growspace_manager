"""Image management for the Strain Library."""

from __future__ import annotations

import base64
import logging
import os
from io import BytesIO

from PIL import Image

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class ImageManager:
    """Manages image processing and storage for the Strain Library."""

    def __init__(self, hass: HomeAssistant, storage_dir: str):
        """Initialize the ImageManager.

        Args:
            hass: Home Assistant instance.
            storage_dir: Directory to store images.
        """
        self.hass = hass
        self.storage_dir = storage_dir
        self._ensure_storage_dir()

    def _ensure_storage_dir(self) -> None:
        """Ensure the storage directory exists."""
        if not os.path.exists(self.storage_dir):
            os.makedirs(self.storage_dir, exist_ok=True)

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

            file_path = os.path.join(self.storage_dir, filename)

            # Save optimized JPEG
            image.save(file_path, "JPEG", quality=85, optimize=True)

            # Return relative path for web access if needed, or absolute path
            # For now returning absolute path as per original logic's intent
            return file_path

        except Exception as e:
            _LOGGER.error("Error saving strain image: %s", e)
            raise

    def get_image_path(self, strain_id: str, phenotype_id: str | None) -> str | None:
        """Get the path to an existing image."""
        filename = f"{strain_id}"
        if phenotype_id:
            filename += f"_{phenotype_id}"
        filename += ".jpg"

        file_path = os.path.join(self.storage_dir, filename)
        if os.path.exists(file_path):
            return file_path
        return None

    def delete_image(self, strain_id: str, phenotype_id: str | None) -> None:
        """Delete an image if it exists."""
        file_path = self.get_image_path(strain_id, phenotype_id)
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError as e:
                _LOGGER.error("Error deleting image %s: %s", file_path, e)
