"""How many modules the renderer's QR will really have.

Print safety for a QR is arithmetic on its module count: how many dots each
module gets, whether the quiet zone survives, whether the matrix fits its
frame at an integer scale. None of that can be asked without knowing the
count, and the count depends on the data, the encoding modes `qrcode` picks
for it and the error-correction level -- not on the frame.

So this module reproduces the version selection of the `qrcode` library the
pinned renderer uses, exactly: the same optimal chunking, the same bit
accounting, the same bisect over the same capacity table, and the same
re-selection when a longer version widens the character-count indicator. It
is a second implementation of one published algorithm (ISO/IEC 18004 table 7
and `qrcode.main.QRCode.best_fit`), not an approximation of it, because a
conservative guess would block layouts that print and a generous one would
authorize layouts that do not.

Nothing here draws a QR. The renderer owns the matrix; this owns its size.
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
import re

#: Bumped when the selection below stops agreeing with the pinned renderer's
#: `qrcode`. A Render Context carries it, so a QR measured under an older
#: model cannot silently authorize a print under a newer one.
QR_MODEL_VERSION = "growspace.qr-model.v1"

#: The largest version the symbology has.
MAX_VERSION = 40

#: Total data bits available per version, per error-correction level. Index 0
#: is unused so the list is indexed by version directly. These are the
#: `qrcode.util.BIT_LIMIT_TABLE` rows, which are themselves derived from the
#: standard's Reed-Solomon block table.
BIT_LIMITS: dict[str, tuple[int, ...]] = {
    "low": (
        0,
        152,
        272,
        440,
        640,
        864,
        1088,
        1248,
        1552,
        1856,
        2192,
        2592,
        2960,
        3424,
        3688,
        4184,
        4712,
        5176,
        5768,
        6360,
        6888,
        7456,
        8048,
        8752,
        9392,
        10208,
        10960,
        11744,
        12248,
        13048,
        13880,
        14744,
        15640,
        16568,
        17528,
        18448,
        19472,
        20528,
        21616,
        22496,
        23648,
    ),
    "medium": (
        0,
        128,
        224,
        352,
        512,
        688,
        864,
        992,
        1232,
        1456,
        1728,
        2032,
        2320,
        2672,
        2920,
        3320,
        3624,
        4056,
        4504,
        5016,
        5352,
        5712,
        6256,
        6880,
        7312,
        8000,
        8496,
        9024,
        9544,
        10136,
        10984,
        11640,
        12328,
        13048,
        13800,
        14496,
        15312,
        15936,
        16816,
        17728,
        18672,
    ),
    "quartile": (
        0,
        104,
        176,
        272,
        384,
        496,
        608,
        704,
        880,
        1056,
        1232,
        1440,
        1648,
        1952,
        2088,
        2360,
        2600,
        2936,
        3176,
        3560,
        3880,
        4096,
        4544,
        4912,
        5312,
        5744,
        6032,
        6464,
        6968,
        7288,
        7880,
        8264,
        8920,
        9368,
        9848,
        10288,
        10832,
        11408,
        12016,
        12656,
        13328,
    ),
    "high": (
        0,
        72,
        128,
        208,
        288,
        368,
        480,
        528,
        688,
        800,
        976,
        1120,
        1264,
        1440,
        1576,
        1784,
        2024,
        2264,
        2504,
        2728,
        3080,
        3248,
        3536,
        3712,
        4112,
        4304,
        4768,
        5024,
        5288,
        5608,
        5960,
        6344,
        6760,
        7208,
        7688,
        7888,
        8432,
        8768,
        9136,
        9776,
        10208,
    ),
}

#: The three encoding modes v1 content can reach, with the bit width of one
#: character-count indicator per version band. Kanji mode is deliberately
#: absent: `qrcode` never selects it for a Python string.
_NUMERIC = "numeric"
_ALPHANUMERIC = "alphanumeric"
_BYTE = "byte"

_COUNT_BITS: dict[str, tuple[int, int, int]] = {
    # versions 1-9, 10-26, 27-40
    _NUMERIC: (10, 12, 14),
    _ALPHANUMERIC: (9, 11, 13),
    _BYTE: (8, 16, 16),
}

#: Bits one chunk of each mode costs, as a function of its character count.
_NUMERIC_REMAINDER = {0: 0, 1: 4, 2: 7}

#: The 45 characters alphanumeric mode can encode.
_ALPHANUMERIC_CHARACTERS = b"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:"

_DIGITS = re.compile(rb"\d{20,}")
_ALPHANUMERIC_RUN = re.compile(b"[" + re.escape(_ALPHANUMERIC_CHARACTERS) + b"]{20,}")
_ALL_DIGITS = re.compile(rb"^\d+$")
_ALL_ALPHANUMERIC = re.compile(b"^[" + re.escape(_ALPHANUMERIC_CHARACTERS) + b"]+$")

#: The run length below which `qrcode` does not bother switching mode. Its
#: `add_data` default, which the renderer does not override.
_OPTIMIZE_MINIMUM = 20


class QrDataOverflow(ValueError):
    """The target does not fit any QR version at the requested correction."""


@dataclass(frozen=True, slots=True)
class QrSymbol:
    """The symbol one target and error-correction level produce."""

    #: 1-40.
    version: int
    #: The matrix's side, in modules, excluding the quiet zone.
    modules: int
    #: Bits the encoded data occupies, which is what chose the version.
    encoded_bits: int

    def side_modules(self, quiet_zone_modules: int) -> int:
        """The painted side, in modules, including both quiet-zone borders."""
        return self.modules + 2 * quiet_zone_modules


def symbol_for(data: str, error_correction: str) -> QrSymbol:
    """Return the symbol the pinned renderer will build for one target."""
    limits = BIT_LIMITS[error_correction]
    chunks = tuple(_chunks(data.encode("utf-8")))

    version = 1
    while True:
        bits = sum(_chunk_bits(mode, length, version) for mode, length in chunks)
        chosen = bisect_left(limits, bits, version)
        if chosen > MAX_VERSION:
            raise QrDataOverflow(
                f"{bits} bits do not fit any {error_correction} QR version"
            )
        if _band(chosen) == _band(version):
            return QrSymbol(version=chosen, modules=chosen * 4 + 17, encoded_bits=bits)
        # A longer version widens the character-count indicators, which can
        # need a longer version still. `qrcode` recurses here and so do we.
        version = chosen


def _band(version: int) -> int:
    """Which of the three character-count-indicator bands a version is in."""
    if version < 10:
        return 0
    if version < 27:
        return 1
    return 2


def _chunks(data: bytes) -> list[tuple[str, int]]:
    """Split one target the way `qrcode.util.optimal_data_chunks` does."""
    if len(data) <= _OPTIMIZE_MINIMUM:
        # Short targets are not split at all; the whole string takes the most
        # compact mode that can carry all of it.
        if _ALL_DIGITS.match(data):
            return [(_NUMERIC, len(data))]
        if _ALL_ALPHANUMERIC.match(data):
            return [(_ALPHANUMERIC, len(data))]
        return [(_BYTE, len(data))]

    chunks: list[tuple[str, int]] = []
    for is_numeric, part in _split(data, _DIGITS):
        if is_numeric:
            chunks.append((_NUMERIC, len(part)))
            continue
        for is_alphanumeric, sub in _split(part, _ALPHANUMERIC_RUN):
            mode = _ALPHANUMERIC if is_alphanumeric else _BYTE
            chunks.append((mode, len(sub)))
    return chunks


def _split(data: bytes, pattern: re.Pattern[bytes]) -> list[tuple[bool, bytes]]:
    """Yield `(matched, part)` runs, keeping the unmatched gaps between them."""
    parts: list[tuple[bool, bytes]] = []
    rest = data
    while rest:
        match = pattern.search(rest)
        if match is None:
            break
        start, end = match.start(), match.end()
        if start:
            parts.append((False, rest[:start]))
        parts.append((True, rest[start:end]))
        rest = rest[end:]
    if rest:
        parts.append((False, rest))
    return parts


def _chunk_bits(mode: str, length: int, version: int) -> int:
    """Bits one chunk costs: mode indicator, character count, then payload."""
    count_bits = _COUNT_BITS[mode][_band(version)]
    return 4 + count_bits + _payload_bits(mode, length)


def _payload_bits(mode: str, length: int) -> int:
    """Bits the characters themselves occupy in one mode."""
    if mode == _NUMERIC:
        return 10 * (length // 3) + _NUMERIC_REMAINDER[length % 3]
    if mode == _ALPHANUMERIC:
        return 11 * (length // 2) + 6 * (length % 2)
    return 8 * length


def dots_per_module(side_pixels: int, side_modules: int) -> int:
    """How many device dots the renderer will give each module.

    The renderer scales a square code to `min(width, height)` by an integer
    factor when enlarging, and by a fractional one when the box is smaller
    than the generated image -- which is where modules stop being uniform.
    Zero therefore means "does not fit", not "very small".
    """
    if side_modules <= 0 or side_pixels <= 0:
        return 0
    return side_pixels // side_modules
