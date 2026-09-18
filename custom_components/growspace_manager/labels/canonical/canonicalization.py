"""RFC 8785 JSON Canonicalization, for the value space label documents admit.

A Label Layout is compared, checksummed, exported and cached by meaning rather
than by whitespace or key order, so every digest in this package is taken over
canonical bytes rather than over whatever a caller happened to serialize.

The scheme is RFC 8785 (JCS). This implementation covers the subset the
canonical label model can contain and **refuses** anything outside it rather
than emitting bytes that only look canonical: no non-finite numbers, no
integers beyond IEEE 754 exact range, and no magnitudes large or small enough
to reach JavaScript's exponential notation. Every one of those is already
impossible in a validated document -- geometry is quantized to 0.01 mm and
counts are small integers -- so the refusal is a guard on the guard, not a
limitation anyone can meet by accident.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json
import math
from typing import Any

#: Beyond this, JavaScript's `Number::toString` switches to exponential
#: notation and a shortest-round-trip Python `repr` stops agreeing with it.
_EXPONENTIAL_ABOVE = 1e21

#: Below this (and non-zero), the same thing happens at the small end.
_EXPONENTIAL_BELOW = 1e-6

#: The range in which an integer is exactly representable as an IEEE 754
#: double, which is what a JSON number is.
_MAX_EXACT_INTEGER = 2**53 - 1


def canonicalize(value: Any) -> bytes:
    """Return the RFC 8785 canonical UTF-8 bytes of one JSON value."""
    return _serialize(value).encode("utf-8")


def digest(value: Any) -> str:
    """Return `sha256:<hex>` over one JSON value's canonical bytes.

    Prefixed with its algorithm because these strings are persisted in Render
    Contexts and cache identities, where a later algorithm change has to be
    visible rather than silently comparing equal.
    """
    return f"sha256:{hashlib.sha256(canonicalize(value)).hexdigest()}"


def _serialize(value: Any) -> str:
    """Serialize one JSON value, recursing into containers."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        # Before `int`: `bool` is a subclass of it and `True` is not `1` here.
        return "true" if value else "false"
    if isinstance(value, str):
        return _serialize_string(value)
    if isinstance(value, int):
        return _serialize_integer(value)
    if isinstance(value, float):
        return _serialize_float(value)
    if isinstance(value, Mapping):
        return _serialize_object(value)
    if isinstance(value, Sequence):
        return "[" + ",".join(_serialize(item) for item in value) + "]"
    raise TypeError(f"{type(value).__name__} is not a canonicalizable JSON value")


def _serialize_object(value: Mapping[Any, Any]) -> str:
    """Serialize a JSON object with its keys in UTF-16 code-unit order.

    Sorting the UTF-16 big-endian encoding rather than the string itself is
    what makes the order RFC 8785's rather than Python's: the two agree across
    the Basic Multilingual Plane and disagree above it.
    """
    members = [
        f"{_serialize_string(key)}:{_serialize(value[key])}"
        for key in sorted(value, key=_utf16_sort_key)
    ]
    return "{" + ",".join(members) + "}"


def _utf16_sort_key(key: Any) -> bytes:
    """Return the UTF-16 sort key of one object member name."""
    if not isinstance(key, str):
        raise TypeError(f"JSON object keys must be strings, got {type(key).__name__}")
    return key.encode("utf-16-be", errors="surrogatepass")


def _serialize_string(value: str) -> str:
    """Serialize a string with JSON's minimal escaping, which is JCS's."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _serialize_integer(value: int) -> str:
    """Serialize an integer, refusing one a JSON number cannot hold exactly."""
    if abs(value) > _MAX_EXACT_INTEGER:
        raise ValueError(f"{value} is outside the exactly representable range")
    return str(value)


def _serialize_float(value: float) -> str:
    """Serialize a double the way ECMAScript's `Number::toString` would.

    Python's `repr` is already the shortest round-tripping representation, so
    the only differences inside the admitted range are the trailing `.0` an
    integral value acquires and the sign of negative zero.
    """
    if not math.isfinite(value):
        raise ValueError(f"{value!r} has no canonical JSON representation")
    magnitude = abs(value)
    if magnitude >= _EXPONENTIAL_ABOVE or (
        magnitude != 0 and magnitude < _EXPONENTIAL_BELOW
    ):
        raise ValueError(f"{value!r} is outside the canonicalizable range")
    if value == 0:
        return "0"
    if value.is_integer():
        return str(int(value))
    return repr(value)
