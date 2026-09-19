"""Tests for the pinned text toolchain seam (hub issue #216).

The two faces a Growspace label prints with belong to the `niimbot`
integration, so this integration resolves them rather than shipping them. That
makes the seam worth its own suite: the production library has to find the
file where the renderer's own resolver finds it, identify the bytes it really
measured, and -- the property everything downstream leans on -- return nothing
rather than a similar face when the file is not there.

The fixtures write Pillow's own bundled TrueType face under the names the
renderer uses. It is not the printer's face and the metrics are not the
printer's metrics; what is being tested is resolution, identity and refusal,
none of which depend on which outlines the file holds.
"""

from __future__ import annotations

from pathlib import Path

from PIL import ImageFont
import pytest

from custom_components.growspace_manager.labels.canonical.fonts import (
    UNRESOLVED_DIGEST,
    NiimbotFontLibrary,
    _file_digest,
    niimbot_font_library,
    toolchain_identity,
)

#: A real TrueType file, borrowed from Pillow's bundled default face.
TRUETYPE = ImageFont.load_default(size=16).path.getvalue()


@pytest.fixture
def font_directory(tmp_path: Path) -> Path:
    """A directory holding the two faces the renderer asks for."""
    directory = tmp_path / "fonts"
    directory.mkdir()
    (directory / "ppb.ttf").write_bytes(TRUETYPE)
    (directory / "rbm.ttf").write_bytes(TRUETYPE)
    return directory


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def test_a_face_resolves_to_the_file_the_renderer_will_rasterize(
    font_directory: Path,
) -> None:
    library = NiimbotFontLibrary([font_directory])
    assert library.path_for("rbm.ttf") == font_directory / "rbm.ttf"


def test_only_the_file_name_is_used_so_a_path_cannot_escape_the_search(
    font_directory: Path,
) -> None:
    library = NiimbotFontLibrary([font_directory])
    assert library.path_for("../../etc/rbm.ttf") == font_directory / "rbm.ttf"


def test_the_nearest_root_wins(tmp_path: Path, font_directory: Path) -> None:
    """The production search order is the printer integration's own: its
    `fonts/` directory first, then Home Assistant's `www/fonts`."""
    nearer = tmp_path / "nearer"
    nearer.mkdir()
    (nearer / "rbm.ttf").write_bytes(TRUETYPE)
    library = NiimbotFontLibrary([nearer, font_directory])
    assert library.path_for("rbm.ttf") == nearer / "rbm.ttf"


def test_a_face_that_is_not_installed_resolves_to_nothing(tmp_path: Path) -> None:
    """Never a fallback: a substituted face would be a different label
    claiming to be this one."""
    library = NiimbotFontLibrary([tmp_path])
    assert library.path_for("rbm.ttf") is None
    assert library.load("rbm.ttf", 20) is None


def test_the_configured_directory_is_searched_before_the_repository(
    tmp_path: Path,
) -> None:
    """The search order is the contract: the printer integration's own fonts
    directory under this installation's configuration, then Home Assistant's
    `www/fonts`, exactly as `niimbot`'s resolver looks."""
    (tmp_path / "custom_components/niimbot/fonts").mkdir(parents=True)
    (tmp_path / "custom_components/niimbot/fonts/rbm.ttf").write_bytes(TRUETYPE)
    (tmp_path / "www" / "fonts").mkdir(parents=True)
    (tmp_path / "www" / "fonts" / "rbm.ttf").write_bytes(TRUETYPE + b"\x00")

    library = niimbot_font_library(str(tmp_path))
    assert library.path_for("rbm.ttf") == (
        tmp_path / "custom_components/niimbot/fonts/rbm.ttf"
    )


def test_an_installation_with_no_configuration_directory_finds_no_face(
    tmp_path: Path,
) -> None:
    """Nothing is inherited from the host: without a configuration directory
    there is only the repository-relative location, which a normal install
    does not hold the printer integration in."""
    assert niimbot_font_library(None).path_for("growspace.no-such-face.ttf") is None


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------


def test_a_resolved_face_measures_and_carries_its_own_identity(
    font_directory: Path,
) -> None:
    library = NiimbotFontLibrary([font_directory])
    face = library.load("rbm.ttf", 20)
    assert face is not None
    assert face.file == "rbm.ttf"
    assert face.size == 20
    assert face.advance("Blue Dream") > 0
    ascent, descent = face.metrics()
    assert ascent > 0 and descent >= 0


def test_a_zero_or_negative_size_still_loads_a_usable_face(
    font_directory: Path,
) -> None:
    """The compiler can round a very small millimetre size to zero pixels, and
    a crash there would be a rendering failure reported as a missing font."""
    library = NiimbotFontLibrary([font_directory])
    face = library.load("rbm.ttf", 0)
    assert face is not None
    assert face.size == 1


def test_a_file_freetype_cannot_read_resolves_to_nothing(tmp_path: Path) -> None:
    (tmp_path / "rbm.ttf").write_bytes(b"not a font")
    library = NiimbotFontLibrary([tmp_path])
    assert library.load("rbm.ttf", 20) is None


def test_missing_glyphs_are_named_and_whitespace_is_never_one(
    font_directory: Path,
) -> None:
    library = NiimbotFontLibrary([font_directory])
    face = library.load("rbm.ttf", 24)
    assert face is not None
    assert face.missing_glyphs("Blue Dream") == ()
    assert face.missing_glyphs("Kush 株") == ("株",)


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


def test_the_digest_is_of_the_bytes_that_were_measured(
    tmp_path: Path, font_directory: Path
) -> None:
    library = NiimbotFontLibrary([font_directory])
    digest = library.digest("rbm.ttf")
    assert digest != UNRESOLVED_DIGEST
    assert library.load("rbm.ttf", 20).digest == digest

    other = tmp_path / "other"
    other.mkdir()
    (other / "rbm.ttf").write_bytes(TRUETYPE + b"\x00")
    assert NiimbotFontLibrary([other]).digest("rbm.ttf") != digest


def test_an_unresolvable_face_has_a_value_rather_than_an_absence(
    tmp_path: Path,
) -> None:
    """ "Measured with nothing" and "measured with these bytes" must not collide
    in a cache identity, so the first is a value too."""
    assert NiimbotFontLibrary([tmp_path]).digest("rbm.ttf") == UNRESOLVED_DIGEST


def test_a_file_that_disappears_between_resolution_and_reading_is_unresolved(
    tmp_path: Path,
) -> None:
    """Resolution and reading are two syscalls apart, and a font directory a
    user is editing can lose a file between them. An unreadable one is
    unresolved rather than an exception out of a render."""
    assert _file_digest(tmp_path / "gone.ttf") == UNRESOLVED_DIGEST


def test_the_toolchain_identity_is_one_digest_per_face(font_directory: Path) -> None:
    library = NiimbotFontLibrary([font_directory])
    identity = toolchain_identity(library, ["rbm.ttf", "ppb.ttf", "rbm.ttf"])
    assert list(identity) == ["ppb.ttf", "rbm.ttf"]
    assert all(value != UNRESOLVED_DIGEST for value in identity.values())
