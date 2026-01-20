"""Image management for the Strain Library."""

from __future__ import annotations

import base64
from datetime import datetime
import hashlib
from io import BytesIO
import logging
from pathlib import Path
from typing import Any, cast

from PIL import Image

from homeassistant.core import HomeAssistant

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
                # Cache both WebP and legacy JPGs
                self._image_cache = {
                    f.name
                    for f in self.storage_dir.glob("*.*")
                    if f.suffix.lower() in (".jpg", ".jpeg", ".webp")
                }
        except OSError as e:
            _LOGGER.error("Error building image cache: %s", e)

    async def async_migrate_to_webp(self, db_connection: Any = None) -> bool:
        """Auto-migrate existing JPG images to WebP format (async wrapper).

        This should be called after initialization to convert legacy JPG files
        to WebP format without blocking the event loop.

        Args:
            db_connection: Optional aiosqlite connection to update image paths in DB.

        Returns:
            True if any migration occurred, False otherwise.
        """
        await self.hass.async_add_executor_job(self._migrate_to_webp_sync)

        # Update database paths if connection provided
        if db_connection:
            updated = await self._update_db_paths(db_connection)
            return updated > 0
        return False

    def _migrate_to_webp_sync(self) -> None:
        """Auto-migrate existing JPG images to WebP format.

        This runs once during initialization to convert any legacy JPG files
        that don't have corresponding WebP variants.
        """
        try:
            if not self.storage_dir.exists():
                _LOGGER.debug(
                    "Image storage directory does not exist yet: %s", self.storage_dir
                )
                return

            jpg_files = list(self.storage_dir.glob("*.jpg")) + list(
                self.storage_dir.glob("*.jpeg")
            )

            _LOGGER.info(
                "Starting WebP migration check - found %d JPG file(s) in %s",
                len(jpg_files),
                self.storage_dir,
            )

            if not jpg_files:
                return

            migrated = 0
            for jpg_path in jpg_files:
                webp_path = jpg_path.with_suffix(".webp")
                small_webp_path = jpg_path.parent / f"{jpg_path.stem}_small.webp"

                # Skip if WebP already exists
                if webp_path.exists() and small_webp_path.exists():
                    continue

                try:
                    img = Image.open(jpg_path)

                    # Convert to RGB if needed
                    if img.mode not in ("RGB", "RGBA"):
                        img = img.convert("RGB")

                    # Save full-size WebP
                    img.save(webp_path, "WEBP", quality=85, method=4)

                    # Save thumbnail
                    thumb_img = img.copy()
                    thumb_img.thumbnail((320, 320))
                    thumb_img.save(small_webp_path, "WEBP", quality=80, method=4)

                    # Update cache
                    self._image_cache.add(webp_path.name)
                    self._image_cache.add(small_webp_path.name)

                    migrated += 1
                    _LOGGER.info(
                        "Migrated %s to WebP format (full + thumbnail)", jpg_path.name
                    )

                except Exception as e:  # noqa: BLE001
                    _LOGGER.warning(
                        "Failed to migrate %s to WebP: %s", jpg_path.name, e
                    )

            if migrated > 0:
                _LOGGER.info(
                    "Auto-migration complete: converted %d image(s) to WebP", migrated
                )

        except Exception as e:  # noqa: BLE001
            _LOGGER.error("Error during auto-migration to WebP: %s", e)

    async def _update_db_paths(self, db_connection: Any) -> int:
        """Update database image_path from .jpg to .webp.

        Args:
            db_connection: aiosqlite database connection.

        Returns:
            Number of database records updated.
        """
        try:
            # Find all phenotypes with .jpg paths
            query = "SELECT phenotype_id, image_path FROM phenotypes WHERE image_path LIKE '%.jpg'"
            async with db_connection.execute(query) as cursor:
                rows = await cursor.fetchall()

            if not rows:
                _LOGGER.debug("No .jpg paths found in database to update")
                return 0

            updated = 0
            for row in rows:
                phenotype_id = row["phenotype_id"]
                old_path = row["image_path"]
                new_path = old_path.replace(".jpg", ".webp")

                await db_connection.execute(
                    "UPDATE phenotypes SET image_path = ? WHERE phenotype_id = ?",
                    (new_path, phenotype_id),
                )
                updated += 1
                _LOGGER.debug(
                    "Updated DB path: %s -> %s (phenotype_id=%d)",
                    old_path,
                    new_path,
                    phenotype_id,
                )

            await db_connection.commit()

            if updated > 0:
                _LOGGER.info("Updated %d database path(s) from .jpg to .webp", updated)

        except Exception as e:  # noqa: BLE001
            _LOGGER.error("Error updating database paths: %s", e)
            return 0
        else:
            return updated

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
        return cast(
            str,
            await self.hass.async_add_executor_job(
                self._save_image_sync, strain_id, phenotype_id, image_base64
            ),
        )

    def _save_image_sync(
        self, strain_id: str, phenotype_id: str | None, image_base64: str
    ) -> str:
        """Synchronous helper to save the image as WebP with a thumbnail."""
        try:
            # Remove header if present
            if "," in image_base64:
                image_base64 = image_base64.split(",")[1]

            image_data = base64.b64decode(image_base64)
            image = Image.open(BytesIO(image_data))

            # Convert to RGB (WebP supports RGBA, but RGB is safer for photos)
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGB")

            # Generate base filename
            base_name = f"{strain_id}"
            if phenotype_id:
                base_name += f"_{phenotype_id}"

            filename = f"{base_name}.webp"
            small_filename = f"{base_name}_small.webp"

            file_path = self.storage_dir / filename
            small_file_path = self.storage_dir / small_filename

            # 1. Save Full Size Optimized WebP
            image.save(file_path, "WEBP", quality=85, method=4)

            # 2. Save Thumbnail (Resize to ~320px width for cards)
            # Copy to avoid modifying the original object in memory if needed later
            thumb_img = image.copy()
            thumb_img.thumbnail((320, 320))
            thumb_img.save(small_file_path, "WEBP", quality=80, method=4)

            # Update cache
            self._image_cache.add(filename)
            self._image_cache.add(small_filename)

            # Return absolute path as string
            return str(file_path.absolute())

        except Exception as e:
            _LOGGER.error("Error saving strain image: %s", e)
            raise

    async def save_timeline_image(
        self, plant_id: str, image_base64: str, timestamp: str | None = None
    ) -> str:
        """Decode and save a timeline image to the storage directory.

        Args:
            plant_id: The ID of the plant.
            image_base64: The base64 encoded image string.
            timestamp: Optional timestamp for unique filename.

        Returns:
            The local path to the saved image.
        """
        return cast(
            str,
            await self.hass.async_add_executor_job(
                self._save_timeline_image_sync, plant_id, image_base64, timestamp
            ),
        )

    def _save_timeline_image_sync(
        self, plant_id: str, image_base64: str, timestamp: str | None = None
    ) -> str:
        """Synchronous helper to save a timeline image in a subdirectory."""
        try:
            # Ensure timeline subdirectory exists
            timeline_dir = self.storage_dir / "timeline"
            timeline_dir.mkdir(parents=True, exist_ok=True)

            # Remove header if present
            if "," in image_base64:
                image_base64 = image_base64.split(",")[1]

            image_data = base64.b64decode(image_base64)
            image = Image.open(BytesIO(image_data))

            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGB")

            # Generate unique filename using plant_id and timestamp/hash
            if not timestamp:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            # Simple hash of image data to prevent duplicates in same timestamp

            data_hash = hashlib.md5(image_data).hexdigest()[:8]

            base_name = f"{plant_id}_{timestamp}_{data_hash}"
            filename = f"{base_name}.webp"
            small_filename = f"{base_name}_small.webp"

            file_path = timeline_dir / filename
            small_file_path = timeline_dir / small_filename

            # Save full and thumbnail
            image.save(file_path, "WEBP", quality=85, method=4)

            thumb_img = image.copy()
            thumb_img.thumbnail((320, 320))
            thumb_img.save(small_file_path, "WEBP", quality=80, method=4)

            # Update cache with relative path from storage_dir
            self._image_cache.add(f"timeline/{filename}")
            self._image_cache.add(f"timeline/{small_filename}")

            return str(file_path.absolute())

        except Exception as e:
            _LOGGER.error("Error saving timeline image: %s", e)
            raise

    def get_image_path(self, strain_id: str, phenotype_id: str | None) -> str | None:
        """Get the path to an existing image using the cache."""
        base_name = f"{strain_id}"
        if phenotype_id:
            base_name += f"_{phenotype_id}"

        # 1. Try WebP first
        webp_name = f"{base_name}.webp"
        if webp_name in self._image_cache:
            return str((self.storage_dir / webp_name).absolute())

        # 2. Fallback to JPG (Legacy support)
        jpg_name = f"{base_name}.jpg"
        if jpg_name in self._image_cache:
            return str((self.storage_dir / jpg_name).absolute())

        return None

    def delete_image(self, strain_id: str, phenotype_id: str | None) -> None:
        """Delete an image and its thumbnail if they exist."""
        base_name = f"{strain_id}"
        if phenotype_id:
            base_name += f"_{phenotype_id}"

        # Define all possible variants to delete
        files_to_delete = [
            f"{base_name}.webp",
            f"{base_name}_small.webp",
            f"{base_name}.jpg",
        ]

        for filename in files_to_delete:
            if filename in self._image_cache:
                file_path = self.storage_dir / filename
                try:
                    if file_path.exists():
                        file_path.unlink()
                    self._image_cache.discard(filename)
                except OSError as e:
                    _LOGGER.error("Error deleting image %s: %s", file_path, e)
