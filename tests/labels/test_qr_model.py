"""Tests for the QR module-count model (hub issue #216).

Whether a QR is safe to print is arithmetic on its module count, and the count
is not a property of the frame -- it comes out of the data, the modes the
generator picks for it and the correction level. The model reproduces the
`qrcode` library the pinned renderer uses, so what follows pins the two things
that would make it wrong in opposite directions: a version that is too small
would authorize a code the renderer will not fit, and one that is too large
would block a code that prints.

The numbers below come from ISO/IEC 18004's capacity tables, which is also
where `qrcode`'s own table comes from. They are cheap to re-derive and they do
not move.
"""

from __future__ import annotations

import pytest

from custom_components.growspace_manager.labels.canonical.qr import (
    MAX_VERSION,
    QrDataOverflow,
    dots_per_module,
    symbol_for,
)

# ---------------------------------------------------------------------------
# Version selection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "correction", "version"),
    [
        # Byte mode, the shape every plant link really takes.
        ("https://example.invalid/p/1", "medium", 3),
        ("https://example.invalid/p/1", "high", 4),
        ("x" * 100, "low", 5),
        ("x" * 100, "high", 10),
        # Numeric and alphanumeric are more compact, and the model has to know
        # it: treating a digit string as bytes would inflate the version and
        # block a code that fits.
        ("9" * 100, "medium", 3),
        ("ABC DEF 123 $%*+-./:" * 3, "medium", 3),
    ],
)
def test_the_version_matches_the_symbology_s_own_capacity(
    data: str, correction: str, version: int
) -> None:
    assert symbol_for(data, correction).version == version


def test_modules_follow_the_version_by_the_standard_s_formula() -> None:
    for data, correction in (("1", "low"), ("x" * 100, "low"), ("x" * 200, "high")):
        symbol = symbol_for(data, correction)
        assert symbol.modules == 4 * symbol.version + 17
    assert symbol_for("1", "low").modules == 21


@pytest.mark.parametrize(
    ("data", "version"),
    [("12345", 1), ("HELLO WORLD", 1), ("Blue Dream \u00e4", 1)],
    ids=["numeric", "alphanumeric", "byte"],
)
def test_a_short_target_takes_one_mode_for_the_whole_string(
    data: str, version: int
) -> None:
    """Below the generator's optimization threshold nothing is split, and the
    whole string takes the most compact mode that can carry all of it --
    reading it as three chunks would choose the wrong version."""
    assert symbol_for(data, "low").version == version


def test_a_short_target_is_not_split_into_chunks() -> None:
    """A digit run inside a short string is not worth a mode switch, so the
    whole thing stays one byte-mode chunk."""
    assert symbol_for("ab123456cd", "low").version == 1


def test_a_long_mixed_target_is_split_the_way_the_generator_splits_it() -> None:
    mixed = "https://example.invalid/plants/" + "9" * 40 + "/label"
    assert symbol_for(mixed, "medium").version == 4


def test_more_correction_needs_a_longer_version_for_the_same_target() -> None:
    low = symbol_for("x" * 200, "low")
    high = symbol_for("x" * 200, "high")
    assert (low.version, high.version) == (9, 15)


def test_a_target_no_version_can_carry_is_refused_rather_than_truncated() -> None:
    with pytest.raises(QrDataOverflow):
        symbol_for("x" * 5000, "high")


def test_the_widest_count_indicator_band_is_reached_by_a_long_target() -> None:
    """Past version 26 the indicator widens a second time, and a model that
    only knew two bands would under-count every large symbol."""
    symbol = symbol_for("x" * 1600, "low")
    assert symbol.version == 29
    assert symbol.modules == 4 * symbol.version + 17


def test_the_widening_count_indicator_is_accounted_for() -> None:
    """Past version 9 the character-count indicator grows, which can need a
    longer version still. A model that selected once would be one short."""
    # 272 bytes need version 10 while the indicator is still 8 bits wide, and
    # version 11 once crossing into band two has widened it to 16.
    symbol = symbol_for("x" * 272, "low")
    assert symbol.version == 11
    assert symbol.version <= MAX_VERSION
    assert symbol_for("x" * 270, "low").version == 10


# ---------------------------------------------------------------------------
# What the renderer does with it
# ---------------------------------------------------------------------------


def test_the_quiet_zone_is_part_of_the_painted_side() -> None:
    symbol = symbol_for("https://example.invalid/p/1", "medium")
    assert symbol.side_modules(4) == symbol.modules + 8


def test_the_module_scale_is_the_integer_the_renderer_would_choose() -> None:
    # 96 device pixels over 37 modules is two dots each, with the remainder
    # simply unused -- the renderer never stretches to fill the box.
    assert dots_per_module(96, 37) == 2
    assert dots_per_module(74, 37) == 2
    assert dots_per_module(73, 37) == 1


def test_a_box_smaller_than_the_matrix_scales_to_nothing() -> None:
    """Zero is "does not fit", not "very small": below one dot per module the
    renderer resizes off the module grid and the code stops being one."""
    assert dots_per_module(36, 37) == 0
    assert dots_per_module(0, 37) == 0
