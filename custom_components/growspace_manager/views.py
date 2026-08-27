"""HTTP Views for the Growspace Manager integration."""

from __future__ import annotations

import contextlib
import logging
import pathlib
import tempfile
from typing import Any, TypeGuard

from aiohttp import BodyPartReader, web

from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .strain_library import StrainLibrary

_LOGGER = logging.getLogger(__name__)


class StrainLibraryUploadView(HomeAssistantView):
    """View to handle strain library imports via HTTP upload."""

    url = "/api/growspace_manager/import_strains"
    name = "api:growspace_manager:import_strains"
    requires_auth = True

    def __init__(
        self,
        hass: HomeAssistant,
        strain_lib: StrainLibrary,
    ) -> None:
        """Initialize the view."""
        self.hass = hass
        self.strain_library = strain_lib

    def _is_valid_upload_field(self, file_field: Any) -> TypeGuard[BodyPartReader]:
        """Validate the uploaded file field."""
        if not file_field:
            return False
        if not isinstance(file_field, BodyPartReader):
            return False
        return bool(file_field.name == "file")

    async def _save_upload_to_temp(self, file_field: BodyPartReader) -> pathlib.Path:
        """Save uploaded stream to a temporary file."""
        _temp_fd, temp_path_str = await self.hass.async_add_executor_job(
            tempfile.mkstemp, ".zip"
        )
        temp_path = pathlib.Path(temp_path_str)

        try:
            # We use a file object opened in binary write mode
            def write_chunk(path: str, data: bytes) -> None:
                with pathlib.Path(path).open("ab") as f:
                    f.write(data)

            while True:
                chunk = await file_field.read_chunk()
                if not chunk:
                    break
                await self.hass.async_add_executor_job(
                    write_chunk, temp_path_str, chunk
                )
        except Exception:
            # Clean up if writing fails
            with contextlib.suppress(OSError, AttributeError):
                await self.hass.async_add_executor_job(temp_path.unlink)
            raise
        else:
            return temp_path

    async def post(self, request: web.Request) -> web.StreamResponse:
        """Handle the POST request for file upload."""
        # 1. Read the multipart data (file)
        reader = await request.multipart()
        file_field = await reader.next()

        if not self._is_valid_upload_field(file_field):
            return web.Response(status=400, text="No file provided or invalid type")

        # 2. Save to temp file
        try:
            temp_path = await self._save_upload_to_temp(file_field)
        except OSError, RuntimeError:
            return web.Response(status=500, text="Failed to save upload")

        try:
            # 3. Process Import
            count = await self.strain_library.import_library_from_zip(
                str(temp_path), merge=True
            )
            await self.strain_library.save()

            # Request refresh for all coordinators
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                if entry.state == ConfigEntryState.LOADED and hasattr(
                    entry, "runtime_data"
                ):
                    await entry.runtime_data.async_request_refresh()

            return self.json({"success": True, "imported_count": count})

        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.exception("Error processing strain library upload")
            return self.json({"success": False, "error": str(err)})

        finally:
            # Cleanup
            with contextlib.suppress(OSError, AttributeError):
                await self.hass.async_add_executor_job(temp_path.unlink)


class StrainLibraryImageView(HomeAssistantView):
    """View to serve images from the strain library storage."""

    url = "/api/growspace_manager/v1/images/{filename:.*}"
    name = "api:growspace_manager:v1:images"
    requires_auth = False  # Images need to be accessible by frontend img tags

    def __init__(
        self,
        hass: HomeAssistant,
        strain_lib: StrainLibrary,
    ) -> None:
        """Initialize the view."""
        self.hass = hass
        self.strain_library = strain_lib

    async def get(self, request: web.Request, filename: str) -> web.StreamResponse:
        """Handle GET request for image."""
        if not self.strain_library.image_manager:
            return web.Response(status=404, text="Image manager not available")

        storage_dir = self.strain_library.image_manager.storage_dir

        # Security check: resolve path and ensure it's within storage_dir
        try:
            file_path = (storage_dir / filename).resolve()
            if not str(file_path).startswith(str(storage_dir.resolve())):
                _LOGGER.warning("Attempted directory traversal access: %s", filename)
                return web.Response(status=403, text="Access denied")

            if not file_path.exists() or not file_path.is_file():
                return web.Response(status=404, text="Image not found")

            return web.FileResponse(file_path)
        except OSError, ValueError, RuntimeError, Exception:
            _LOGGER.exception("Error serving image %s", filename)
            return web.Response(status=500, text="Internal server error")
