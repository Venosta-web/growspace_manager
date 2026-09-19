"""The pinned text toolchain, and what the backend can measure with it.

Text is the one element variant whose ink cannot be derived from its frame.
Whether a strain name fits, where it sits inside its box, which glyphs the
face actually has and how small it ended up are all questions only the font
file can answer -- and the file belongs to the printer integration, not to
this one.

So the toolchain is a seam rather than an import. A [[Font Library]] resolves
a Style Token's file to something that can measure and rasterize it; the
production one looks exactly where the `niimbot` renderer looks, and returns
nothing when the file is not there. Nothing downstream substitutes a similar
face: an unresolvable font is reported as an unmeasured toolchain, and every
check that needed a measurement says so rather than guessing.

The library also produces the toolchain identity a Render Context carries --
the digest of the bytes that were measured, so a font update invalidates a
cached raster without anyone pretending the saved layout changed.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import lru_cache
import hashlib
from pathlib import Path
from typing import Protocol

from PIL import Image, ImageDraw, ImageFont

#: Bumped when measurement or rasterization here stops matching the pinned
#: renderer's own.
TEXT_TOOLCHAIN_VERSION = "growspace.text-toolchain.v1"

#: What a Render Context records when no font file could be resolved. It is a
#: value rather than an absence so that "measured with nothing" and "measured
#: with these bytes" cannot collide in a cache identity.
UNRESOLVED_DIGEST = "unresolved"

#: A codepoint no real face carries, used to recognise the `.notdef` glyph a
#: missing character renders as. FreeType answers every unmapped codepoint
#: with the same bitmap, so a character that rasterizes identically to this
#: one is a character the face does not have.
_NOTDEF_PROBE = "\U0010fffd"

#: Where the printer integration keeps the two faces it ships.
_NIIMBOT_FONT_DIRECTORY = Path("custom_components/niimbot/fonts")


@dataclass(frozen=True, slots=True)
class MeasuredFont:
    """One font file at one pixel size, as the renderer will use it."""

    file: str
    size: int
    digest: str
    face: ImageFont.FreeTypeFont

    def advance(self, text: str) -> float:
        """The pen advance of one line, in device pixels."""
        return self.face.getlength(text)

    def metrics(self) -> tuple[int, int]:
        """Ascent and descent, which together give the renderer's line box."""
        return self.face.getmetrics()

    def missing_glyphs(self, text: str) -> tuple[str, ...]:
        """Return the characters of `text` this face cannot draw.

        Whitespace is excluded: a space has no outline in any face, so
        comparing its bitmap against `.notdef` proves nothing.
        """
        notdef = self._rasterized(_NOTDEF_PROBE)
        missing: list[str] = []
        for character in dict.fromkeys(text):
            if character.isspace():
                continue
            if self._rasterized(character) == notdef:
                missing.append(character)
        return tuple(missing)

    def draw_line(
        self,
        draw: ImageDraw.ImageDraw,
        position: tuple[int, int],
        text: str,
        anchor: str,
    ) -> None:
        """Draw one line into an ink mask, the way the renderer draws it."""
        draw.text(position, text, fill=1, font=self.face, anchor=anchor)

    def _rasterized(self, character: str) -> tuple[tuple[int, int], bytes]:
        """The bitmap one character produces, as a comparable value."""
        mask = self.face.getmask(character, mode="1")
        return mask.size, bytes(mask)


class FontLibrary(Protocol):
    """Resolves a Style Token's font file to something measurable."""

    def load(self, file: str, size: int) -> MeasuredFont | None:
        """Return the face at `size`, or `None` when the file is absent."""

    def digest(self, file: str) -> str:
        """Return the identity of the bytes `file` resolves to."""


class NiimbotFontLibrary:
    """The production library: the two faces the printer integration ships.

    It looks where `niimbot`'s own font resolver looks, in the same order, so
    the backend measures the file the renderer will rasterize rather than a
    same-named one from somewhere else. When neither location has it, the
    answer is `None` -- never a fallback face.
    """

    def __init__(self, roots: Iterable[Path]) -> None:
        """Prepare the search path, nearest first."""
        self._roots = tuple(roots)

    def path_for(self, file: str) -> Path | None:
        """Resolve one font file name to the bytes that will be rasterized."""
        name = Path(file).name
        for root in self._roots:
            candidate = root / name
            if candidate.is_file():
                return candidate
        return None

    def load(self, file: str, size: int) -> MeasuredFont | None:
        """Load one face at one pixel size, or report that it is not here."""
        path = self.path_for(file)
        if path is None:
            return None
        return _measured(path, max(size, 1))

    def digest(self, file: str) -> str:
        """Return a short digest of the resolved file's bytes."""
        path = self.path_for(file)
        if path is None:
            return UNRESOLVED_DIGEST
        return _file_digest(path)


def niimbot_font_library(config_directory: str | None) -> NiimbotFontLibrary:
    """Build the production library for one Home Assistant configuration."""
    roots = [Path(__file__).resolve().parents[4] / _NIIMBOT_FONT_DIRECTORY]
    if config_directory:
        base = Path(config_directory)
        roots = [base / _NIIMBOT_FONT_DIRECTORY, base / "www" / "fonts", *roots]
    return NiimbotFontLibrary(roots)


def toolchain_identity(library: FontLibrary, files: Iterable[str]) -> Mapping[str, str]:
    """Return one digest per font file, for the Render Context to carry."""
    return {file: library.digest(file) for file in sorted(set(files))}


@lru_cache(maxsize=64)
def _measured(path: Path, size: int) -> MeasuredFont | None:
    """Load and cache one face, or report a file FreeType cannot read."""
    try:
        font = ImageFont.truetype(str(path), size)
    except OSError, ValueError:
        return None
    return MeasuredFont(file=path.name, size=size, digest=_file_digest(path), face=font)


@lru_cache(maxsize=16)
def _file_digest(path: Path) -> str:
    """Return a short content digest of one font file."""
    try:
        payload = path.read_bytes()
    except OSError:
        return UNRESOLVED_DIGEST
    return hashlib.sha256(payload).hexdigest()[:16]


def new_mask(width: int, height: int) -> Image.Image:
    """Return an empty one-bit ink mask of one raster's size."""
    return Image.new("1", (max(width, 1), max(height, 1)), 0)
