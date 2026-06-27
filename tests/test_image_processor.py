"""Tests for GrowspaceImageProcessor (Pillow + numpy implementation)."""

from __future__ import annotations

import io

import numpy as np
from PIL import Image
import pytest

from custom_components.growspace_manager.image_processor import (
    _GREEN_LOWER,
    _GREEN_UPPER,
    _GRID_ROWS,
    GrowspaceImageProcessor,
    _rgb_to_hsv_ocv,
)

# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------


def _make_solid_image(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    """Return PNG bytes for a solid-color image."""
    arr = np.full((height, width, 3), rgb, dtype=np.uint8)
    img = Image.fromarray(arr)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_split_image(
    width: int,
    height: int,
    top_rgb: tuple[int, int, int],
    bottom_rgb: tuple[int, int, int],
) -> bytes:
    """Return PNG bytes where the top half is top_rgb and the bottom half is bottom_rgb."""
    arr = np.zeros((height, width, 3), dtype=np.uint8)
    mid = height // 2
    arr[:mid, :] = top_rgb
    arr[mid:, :] = bottom_rgb
    img = Image.fromarray(arr)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# Plant green well within the HSV threshold: H≈60 (OCV), S=255, V=180
_GREEN_RGB = (0, 180, 0)
# Colors clearly outside the green band
_RED_RGB = (220, 20, 20)
_BLUE_RGB = (20, 20, 220)


# ---------------------------------------------------------------------------
# HSV conversion unit tests
# ---------------------------------------------------------------------------


def test_rgb_to_hsv_ocv_pure_green():
    """Pure green RGB maps to hue ≈ 60 in OpenCV scale (range 35–85)."""
    arr = np.array([[[0, 180, 0]]], dtype=np.uint8)
    hsv = _rgb_to_hsv_ocv(arr)
    h, s, v = int(hsv[0, 0, 0]), int(hsv[0, 0, 1]), int(hsv[0, 0, 2])
    assert 35 <= h <= 85, f"Expected hue 35-85, got {h}"
    assert s > 200
    assert v > 100


def test_rgb_to_hsv_ocv_pure_red_outside_green_band():
    """Pure red maps to hue 0, which is outside the green detection band."""
    arr = np.array([[[220, 20, 20]]], dtype=np.uint8)
    hsv = _rgb_to_hsv_ocv(arr)
    h = int(hsv[0, 0, 0])
    assert not (_GREEN_LOWER[0] <= h <= _GREEN_UPPER[0]), f"Red hue {h} should not be in green range"


def test_rgb_to_hsv_ocv_gray_low_saturation():
    """Gray has near-zero saturation, below the green saturation floor."""
    arr = np.array([[[128, 128, 128]]], dtype=np.uint8)
    hsv = _rgb_to_hsv_ocv(arr)
    s = int(hsv[0, 0, 1])
    assert s < _GREEN_LOWER[1], f"Gray saturation {s} should be below green floor {_GREEN_LOWER[1]}"


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------


def test_process_snapshot_returns_bytes_and_float():
    """process_snapshot returns a (bytes, float) tuple."""
    data = _make_solid_image(50, 50, _GREEN_RGB)
    result = GrowspaceImageProcessor().process_snapshot(data)
    assert isinstance(result, tuple) and len(result) == 2
    assert isinstance(result[0], bytes)
    assert isinstance(result[1], float)


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_process_snapshot_invalid_bytes_raises_value_error():
    """ValueError is raised when the bytes are not a valid image."""
    with pytest.raises(ValueError, match="[Dd]ecode"):
        GrowspaceImageProcessor().process_snapshot(b"definitely_not_an_image")


def test_process_snapshot_empty_bytes_raises_value_error():
    """ValueError is raised on empty input."""
    with pytest.raises(ValueError):
        GrowspaceImageProcessor().process_snapshot(b"")


# ---------------------------------------------------------------------------
# Coverage calculation
# ---------------------------------------------------------------------------


def test_process_snapshot_coverage_zero_for_non_green_image():
    """Coverage is 0.0 for a fully red image (no green pixels)."""
    data = _make_solid_image(50, 50, _RED_RGB)
    _, coverage = GrowspaceImageProcessor().process_snapshot(data)
    assert coverage == 0.0


def test_process_snapshot_coverage_nonzero_for_green_image():
    """Coverage is substantially above 0 for a fully green image."""
    data = _make_solid_image(100, 100, _GREEN_RGB)
    _, coverage = GrowspaceImageProcessor().process_snapshot(data)
    # Solid plant-green should yield high coverage
    assert coverage > 50.0, f"Expected >50% for solid green image, got {coverage}%"


def test_process_snapshot_coverage_half_green():
    """Coverage is approximately 50% for a half-green, half-red image."""
    data = _make_split_image(100, 100, top_rgb=_GREEN_RGB, bottom_rgb=_RED_RGB)
    _, coverage = GrowspaceImageProcessor().process_snapshot(data)
    # Allow some tolerance for JPEG re-encoding rounding at the border
    assert 30.0 <= coverage <= 70.0, f"Expected ~50% coverage, got {coverage}%"


def test_process_snapshot_coverage_is_float():
    """Coverage value is a Python float."""
    data = _make_solid_image(50, 50, _GREEN_RGB)
    _, coverage = GrowspaceImageProcessor().process_snapshot(data)
    assert isinstance(coverage, float)


def test_process_snapshot_coverage_within_bounds():
    """Coverage is always in the range 0.0–100.0."""
    for rgb in [_GREEN_RGB, _RED_RGB, _BLUE_RGB, (128, 128, 128)]:
        data = _make_solid_image(50, 50, rgb)
        _, coverage = GrowspaceImageProcessor().process_snapshot(data)
        assert 0.0 <= coverage <= 100.0, f"Coverage out of bounds for {rgb}: {coverage}"


# ---------------------------------------------------------------------------
# Output encoding
# ---------------------------------------------------------------------------


def test_process_snapshot_output_is_valid_jpeg():
    """The returned bytes are a valid JPEG (starts with FF D8 FF)."""
    data = _make_solid_image(50, 50, _GREEN_RGB)
    out_bytes, _ = GrowspaceImageProcessor().process_snapshot(data)
    assert out_bytes[:3] == b"\xff\xd8\xff", "Output is not a valid JPEG"


def test_process_snapshot_accepts_jpeg_input():
    """process_snapshot handles JPEG input without error."""
    arr = np.full((50, 50, 3), _GREEN_RGB, dtype=np.uint8)
    img = Image.fromarray(arr)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    out_bytes, coverage = GrowspaceImageProcessor().process_snapshot(buf.getvalue())
    assert isinstance(out_bytes, bytes)
    assert isinstance(coverage, float)


def test_process_snapshot_non_rgb_image_is_converted():
    """RGBA input is converted to RGB without error."""
    arr = np.full((50, 50, 4), (0, 180, 0, 255), dtype=np.uint8)
    img = Image.fromarray(arr, mode="RGBA")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    out_bytes, _ = GrowspaceImageProcessor().process_snapshot(buf.getvalue())
    assert out_bytes[:3] == b"\xff\xd8\xff"


# ---------------------------------------------------------------------------
# Grid overlay — verify via output image inspection
# ---------------------------------------------------------------------------


def _load_output_image(out_bytes: bytes) -> np.ndarray:
    """Load JPEG bytes back into a numpy RGB array."""
    return np.array(Image.open(io.BytesIO(out_bytes)).convert("RGB"))


def test_process_snapshot_grid_adds_magenta_lines():
    """The output image contains magenta pixels where grid lines were drawn."""
    # Use a gray image so any magenta pixel must be from the grid
    data = _make_solid_image(200, 200, (100, 100, 100))
    out_bytes, _ = GrowspaceImageProcessor().process_snapshot(data)
    arr = _load_output_image(out_bytes)

    # Magenta = high R, low G, high B — search for pixels with R>200, G<50, B>200
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    magenta_mask = (r > 180) & (g < 80) & (b > 180)
    assert np.any(magenta_mask), "No magenta grid line pixels found in output"


def test_process_snapshot_grid_lines_at_expected_positions():
    """Horizontal grid lines appear at 1/4, 2/4, and 3/4 of image height."""
    size = 200
    data = _make_solid_image(size, size, (100, 100, 100))
    out_bytes, _ = GrowspaceImageProcessor().process_snapshot(data)
    arr = _load_output_image(out_bytes)

    cell = size // _GRID_ROWS  # 50px
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]

    for row_idx in range(1, _GRID_ROWS):
        y = row_idx * cell
        row_slice = (r[y, :] > 180) & (g[y, :] < 80) & (b[y, :] > 180)
        assert np.any(row_slice), f"Expected magenta grid line at y={y}"


def test_process_snapshot_output_dimensions_unchanged():
    """The output image has the same width and height as the input."""
    data = _make_solid_image(160, 120, _GREEN_RGB)
    out_bytes, _ = GrowspaceImageProcessor().process_snapshot(data)
    out_img = Image.open(io.BytesIO(out_bytes))
    assert out_img.size == (160, 120)


def test_process_snapshot_old_pillow_font_fallback():
    """Test font fallback for Pillow < 10.1 where load_default doesn't accept size (image_processor.py:129-131)."""
    from unittest.mock import patch

    from PIL import ImageFont

    data = _make_solid_image(160, 120, _GREEN_RGB)

    original_load_default = ImageFont.load_default

    def _raise_on_size(**kwargs):
        if "size" in kwargs:
            raise TypeError("load_default() got an unexpected keyword argument 'size'")
        return original_load_default()

    with patch("custom_components.growspace_manager.image_processor.ImageFont.load_default", side_effect=_raise_on_size):
        out_bytes, _ = GrowspaceImageProcessor().process_snapshot(data)

    assert len(out_bytes) > 0
