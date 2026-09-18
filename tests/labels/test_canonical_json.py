"""Tests for RFC 8785 canonicalization (hub issue #214).

Every layout digest, content-snapshot identity and preview cache identity is
a hash of these bytes, so a disagreement here is a disagreement about whether
two renders are the same render. The rules that earn their own tests are the
two a naive `json.dumps` gets wrong: ECMAScript number spelling, and sorting
object members by UTF-16 code unit rather than by code point.

The refusals matter as much. A value this scheme cannot represent exactly
must raise rather than produce bytes that only look canonical -- a silently
wrong digest is a cache that serves the wrong label.
"""

from __future__ import annotations

from typing import Any

import pytest

from custom_components.growspace_manager.labels.canonical.canonicalization import (
    canonicalize,
    digest,
)

# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------


def test_object_members_are_sorted_and_whitespace_is_dropped() -> None:
    assert canonicalize({"b": 1, "a": [1, 2]}) == b'{"a":[1,2],"b":1}'


def test_members_sort_by_utf16_code_unit_rather_than_code_point() -> None:
    """The one place Python's own ordering disagrees with RFC 8785.

    U+1F600 is the surrogate pair D83D DE00 in UTF-16, so it sorts *before*
    U+FFFD there and *after* it by code point. Sorting the strings directly
    would put them the other way round.
    """
    canonical = canonicalize({"�": 1, "\U0001f600": 2}).decode()
    assert canonical.index('"\U0001f600"') < canonical.index('"�"')
    assert sorted(["�", "\U0001f600"]) == ["�", "\U0001f600"]


def test_containers_nest() -> None:
    assert (
        canonicalize({"a": [{"z": None}, {"y": True}]})
        == b'{"a":[{"z":null},{"y":true}]}'
    )


def test_an_empty_object_and_an_empty_array_are_distinct() -> None:
    assert canonicalize({"a": {}, "b": []}) == b'{"a":{},"b":[]}'


def test_the_output_is_utf8_bytes() -> None:
    assert canonicalize({"name": "Blüte"}) == '{"name":"Blüte"}'.encode()


# ---------------------------------------------------------------------------
# Scalars
# ---------------------------------------------------------------------------


def test_null_and_the_two_booleans_are_json_keywords() -> None:
    assert (
        canonicalize({"a": None, "b": True, "c": False})
        == b'{"a":null,"b":true,"c":false}'
    )


def test_a_boolean_is_not_the_integer_it_subclasses() -> None:
    """`True == 1` in Python, and `true` is not `1` in JSON."""
    assert canonicalize([True, 1]) == b"[true,1]"


def test_a_whole_number_canonicalizes_without_a_trailing_zero() -> None:
    """RFC 8785 numbers are ECMAScript numbers; `3.0` and `3` are one value."""
    assert canonicalize({"x_mm": 3.0}) == b'{"x_mm":3}'
    assert canonicalize({"x_mm": 4.2}) == b'{"x_mm":4.2}'


def test_a_whole_float_and_its_integer_hash_identically() -> None:
    """Which is why a frame at `3` and a frame at `3.0` are one frame."""
    assert digest({"x_mm": 3.0}) == digest({"x_mm": 3})


def test_negative_zero_is_zero() -> None:
    assert canonicalize({"x_mm": -0.0}) == b'{"x_mm":0}'


def test_a_quantized_millimetre_round_trips_to_its_shortest_spelling() -> None:
    assert canonicalize([0.01, 26.6, 48.05, -3.25]) == b"[0.01,26.6,48.05,-3.25]"


def test_control_characters_escape_and_other_text_does_not() -> None:
    assert canonicalize({"a": "x\nyz"}) == b'{"a":"x\\ny\\u0001z"}'


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
def test_a_non_finite_number_has_no_canonical_form(value: float) -> None:
    with pytest.raises(ValueError, match="canonical JSON"):
        canonicalize({"x_mm": value})


@pytest.mark.parametrize("value", [1e21, -1e21, 1e-7, -1e-7])
def test_a_magnitude_that_would_reach_exponential_notation_is_refused(
    value: float,
) -> None:
    """Shortest-round-trip `repr` stops agreeing with ECMAScript out there."""
    with pytest.raises(ValueError, match="canonicalizable range"):
        canonicalize({"x_mm": value})


def test_an_integer_a_json_number_cannot_hold_exactly_is_refused() -> None:
    with pytest.raises(ValueError, match="exactly representable"):
        canonicalize({"count": 2**53})
    assert canonicalize({"count": 2**53 - 1}) == b'{"count":9007199254740991}'


@pytest.mark.parametrize("value", [{1, 2}, object(), b"bytes", 1j])
def test_a_value_that_is_not_json_is_refused(value: Any) -> None:
    with pytest.raises(TypeError, match="canonicalizable JSON value"):
        canonicalize({"a": value})


def test_a_non_string_object_key_is_refused() -> None:
    with pytest.raises(TypeError, match="keys must be strings"):
        canonicalize({1: "one"})


# ---------------------------------------------------------------------------
# Digests
# ---------------------------------------------------------------------------


def test_a_digest_names_its_algorithm() -> None:
    """Persisted in Render Contexts, so a later algorithm cannot compare equal."""
    assert digest({"a": 1}).startswith("sha256:")


def test_a_digest_is_of_meaning_rather_than_of_spelling() -> None:
    assert digest({"a": 1, "b": 2}) == digest({"b": 2, "a": 1})
    assert digest({"a": 1}) != digest({"a": 2})
