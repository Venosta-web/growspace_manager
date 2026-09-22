"""Rectangles: millimetres on the stock, and device pixels on the raster.

Two coordinate systems meet in one render, and conflating them is how a
"printable area" ends up compared against a frame that was never translated
into it. So they are separate types here. An [[Area]] is millimetres in the
stock's own unrotated coordinate system, which is where a Capability Profile
declares its physical regions; a [[Pixel Frame]] is device pixels on the
raster the compiler builds, whose origin is the Printable Area's top-left.

Nothing in this module moves anything. Containment and intersection are
questions, and a question that answers "no" produces a diagnostic upstream
rather than a corrected rectangle.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AreaMm:
    """One axis-aligned physical region, in the stock's millimetres."""

    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float

    @property
    def right_mm(self) -> float:
        """The region's right edge."""
        return self.x_mm + self.width_mm

    @property
    def bottom_mm(self) -> float:
        """The region's bottom edge."""
        return self.y_mm + self.height_mm

    def inset_by(self, millimetres: float) -> AreaMm:
        """Return this region inset on all four sides.

        An inset larger than the region collapses it to zero extent rather
        than inverting it: a profile whose Safe Area swallowed its Printable
        Area must read as "nothing is safe", not as a negative rectangle that
        every later containment test silently passes.
        """
        width = max(self.width_mm - 2 * millimetres, 0.0)
        height = max(self.height_mm - 2 * millimetres, 0.0)
        return AreaMm(
            x_mm=self.x_mm + (self.width_mm - width) / 2,
            y_mm=self.y_mm + (self.height_mm - height) / 2,
            width_mm=width,
            height_mm=height,
        )

    def as_dict(self) -> dict[str, float]:
        """Return the region's wire form."""
        return {
            "x_mm": self.x_mm,
            "y_mm": self.y_mm,
            "width_mm": self.width_mm,
            "height_mm": self.height_mm,
        }


@dataclass(frozen=True, slots=True)
class PixelFrame:
    """One element's compiled extent, in device pixels on the raster."""

    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        """Pixel width, as the difference of two converted edges."""
        return self.right - self.left

    @property
    def height(self) -> int:
        """Pixel height, as the difference of two converted edges."""
        return self.bottom - self.top

    @property
    def is_empty(self) -> bool:
        """Whether this frame encloses no pixel at all."""
        return self.width <= 0 or self.height <= 0

    def contains(self, other: PixelFrame) -> bool:
        """Whether `other` lies wholly inside this frame."""
        return (
            other.left >= self.left
            and other.top >= self.top
            and other.right <= self.right
            and other.bottom <= self.bottom
        )

    def intersection(self, other: PixelFrame) -> PixelFrame | None:
        """Return the overlapping rectangle, or `None` when there is none."""
        left = max(self.left, other.left)
        top = max(self.top, other.top)
        right = min(self.right, other.right)
        bottom = min(self.bottom, other.bottom)
        if right <= left or bottom <= top:
            return None
        return PixelFrame(left=left, top=top, right=right, bottom=bottom)

    def as_dict(self) -> dict[str, int]:
        """Return the frame's wire form."""
        return {
            "left": self.left,
            "top": self.top,
            "right": self.right,
            "bottom": self.bottom,
            "width": self.width,
            "height": self.height,
        }
