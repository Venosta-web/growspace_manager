"""Image processor for growspace camera snapshots.

Provides deterministic, CPU-based image preparation before sending
snapshots to a cloud VLM. Uses Pillow and numpy — both pure-Python /
pre-built-wheel packages — to avoid native compilation in HA's environment.

All processing is synchronous and CPU-bound; callers must run this via
``hass.async_add_executor_job`` to avoid blocking the event loop.
"""

from __future__ import annotations

import io
import logging

import numpy as np
from PIL import Image, ImageDraw, ImageFont

_LOGGER = logging.getLogger(__name__)

# HSV color bounds for plant foliage under white LED grow lights.
# Uses OpenCV-compatible scale: H 0-179 (half of 360°), S/V 0-255.
# Hue 35-85 covers yellow-green through pure green.
# Saturation/value floors of 40 filter out dull shadows and white hotspots.
_GREEN_LOWER = (35, 40, 40)
_GREEN_UPPER = (85, 255, 255)

_GRID_ROWS = 4
_GRID_COLS = 4

# Row A–D, column 1–4 → A1 … D4
_GRID_LABELS: list[list[str]] = [
    [f"{chr(65 + r)}{c + 1}" for c in range(_GRID_COLS)] for r in range(_GRID_ROWS)
]

# RGB color palette (Pillow uses RGB tuples)
_GRID_COLOR = (255, 0, 255)  # Magenta grid lines
_TEXT_FG = (0, 255, 255)  # Cyan label text (contrasts with green canopy)
_TEXT_BG = (0, 0, 0)  # Black outline for legibility on any background


def _rgb_to_hsv_ocv(rgb: np.ndarray) -> np.ndarray:
    """Convert a uint8 RGB array to HSV with OpenCV-compatible scale.

    Output: H 0–179 (half of 360°), S 0–255, V 0–255.
    """
    r = rgb[..., 0].astype(np.float32) / 255.0
    g = rgb[..., 1].astype(np.float32) / 255.0
    b = rgb[..., 2].astype(np.float32) / 255.0

    cmax = np.maximum(np.maximum(r, g), b)
    cmin = np.minimum(np.minimum(r, g), b)
    delta = cmax - cmin

    h = np.zeros_like(r)
    nonzero = delta > 1e-7
    r_max = (cmax == r) & nonzero
    g_max = (cmax == g) & nonzero
    b_max = (cmax == b) & nonzero

    h[r_max] = ((g[r_max] - b[r_max]) / delta[r_max]) % 6.0
    h[g_max] = (b[g_max] - r[g_max]) / delta[g_max] + 2.0
    h[b_max] = (r[b_max] - g[b_max]) / delta[b_max] + 4.0

    # Scale to OpenCV hue range 0–179 (60° sectors × 30 = 180 total, clipped to 179)
    h_out = np.clip(h * 30.0, 0, 179).astype(np.uint8)

    s_out = np.where(cmax > 1e-7, delta / cmax, 0.0)
    s_out = np.clip(s_out * 255.0, 0, 255).astype(np.uint8)

    v_out = np.clip(cmax * 255.0, 0, 255).astype(np.uint8)

    return np.stack([h_out, s_out, v_out], axis=-1)


class GrowspaceImageProcessor:
    """Processes camera snapshots for canopy coverage and grid overlay."""

    def process_snapshot(self, image_bytes: bytes) -> tuple[bytes, float]:
        """Process a raw camera snapshot (CPU-bound; use async_add_executor_job).

        Steps:
        1. Decode the image with Pillow.
        2. Convert to HSV via numpy and create a green-pixel mask to measure
           canopy density.
        3. Draw a labeled 4x4 grid overlay for spatial reference in AI analysis.
        4. Re-encode to JPEG.

        Args:
            image_bytes: Raw JPEG or PNG bytes from the camera.

        Returns:
            Tuple of (processed_jpeg_bytes, canopy_coverage_percent).
            Coverage is a float in the range 0.0–100.0.

        Raises:
            ValueError: If the image cannot be decoded or re-encoded.

        """
        try:
            img: Image.Image = Image.open(io.BytesIO(image_bytes))
        except Exception as exc:
            raise ValueError(
                f"Could not decode the supplied image bytes: {exc}"
            ) from exc

        if img.mode != "RGB":
            img = img.convert("RGB")

        w, h = img.size
        total_pixels = w * h

        # --- Canopy Coverage ---
        rgb = np.array(img, dtype=np.uint8)
        hsv = _rgb_to_hsv_ocv(rgb)
        lower = np.array(_GREEN_LOWER, dtype=np.uint8)
        upper = np.array(_GREEN_UPPER, dtype=np.uint8)
        mask = np.all((hsv >= lower) & (hsv <= upper), axis=-1)
        green_pixels = int(np.count_nonzero(mask))
        coverage = round(green_pixels / total_pixels * 100, 1) if total_pixels else 0.0

        # --- 4x4 Grid Overlay ---
        cell_w = w // _GRID_COLS
        cell_h = h // _GRID_ROWS
        font_size = max(14, min(w, h) // 30)

        draw = ImageDraw.Draw(img)

        try:
            font = ImageFont.load_default(size=font_size)
        except TypeError:
            # Pillow < 10.1 fallback
            font = ImageFont.load_default()

        # Horizontal and vertical dividers
        for r in range(1, _GRID_ROWS):
            draw.line([(0, r * cell_h), (w, r * cell_h)], fill=_GRID_COLOR, width=2)
        for c in range(1, _GRID_COLS):
            draw.line([(c * cell_w, 0), (c * cell_w, h)], fill=_GRID_COLOR, width=2)

        # Sector labels with black outline for legibility on any background
        for r in range(_GRID_ROWS):
            for c in range(_GRID_COLS):
                label = _GRID_LABELS[r][c]
                x = c * cell_w + 4
                y = r * cell_h + 4
                # Eight-direction outline
                for dx in range(-1, 2):
                    for dy in range(-1, 2):
                        if dx != 0 or dy != 0:
                            draw.text((x + dx, y + dy), label, fill=_TEXT_BG, font=font)
                draw.text((x, y), label, fill=_TEXT_FG, font=font)

        # --- Re-encode ---
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        return buf.getvalue(), coverage
