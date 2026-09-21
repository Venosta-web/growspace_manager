"""The localization catalogue the card translates against (hub issue #230).

Printable captions and domain values are the backend's to localize; stable
codes -- diagnostics, refusals, eligibility blockers -- are the card's. That
split only holds if the card knows every code it can be sent and every named
value it may interpolate, so the backend publishes the complete set as a
contract fixture and the card's suite refuses a code it has no reviewed copy
for.

This suite keeps the published set honest: every code literal in the source
is declared, every declared code is still produced somewhere, and the fixture
is exactly what the catalogue says. `tests/labels/conftest.py` holds every
diagnostic the product emits during the label suites to the same catalogue.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
import re
from typing import Any

import pytest

from custom_components.growspace_manager.exceptions import EntityNotFoundError
from custom_components.growspace_manager.labels import capability
from custom_components.growspace_manager.labels.canonical import SUPPORTED_LOCALES
from custom_components.growspace_manager.labels.canonical.diagnostics import (
    DIAGNOSTIC_CATALOGUE,
    Diagnostic,
    Layer,
    Severity,
)
from custom_components.growspace_manager.labels.canonical.eligibility import Blocker
from custom_components.growspace_manager.labels.library import errors as library_errors
from custom_components.growspace_manager.labels.library.errors import LabelTemplateError
from custom_components.growspace_manager.websocket import (
    drafts,
    label_batch,
    label_printing,
    labels,
)

PACKAGE = Path(__file__).parents[2] / "custom_components" / "growspace_manager"
FIXTURE = (
    Path(__file__).parent.parent
    / "fixtures"
    / "contract"
    / "label_localization_catalogue_v1.json"
)

#: The layer prefixes diagnostic codes are spelled with. Binding identities
#: (`strain.name`, `plant.link`, `print.date`) share the dotted shape and are
#: deliberately not in this list.
DIAGNOSTIC_PREFIX = re.compile(
    r"^(content|document|element|frame|geometry|profile|raster|schema|style"
    r"|transport)\.[a-z_]+$"
)


def _refusal_codes() -> list[str]:
    """Every refusal code a label WebSocket command can answer with.

    Two spellings reach the card. Most commands refuse with a literal
    `label_template.<snake_case>` code; the management command refuses a
    library error by its class name, `label_template.<ErrorName>`, so every
    library error class is a code too.
    """
    codes = _source_literals(re.compile(r"^label_template\.[a-z_]+$"))
    codes.update(
        f"label_template.{name}"
        for name, value in vars(library_errors).items()
        if isinstance(value, type)
        and issubclass(value, (LabelTemplateError, EntityNotFoundError))
        and value.__module__ == library_errors.__name__
        and value is not LabelTemplateError
    )
    return sorted(codes)


def _source_literals(pattern: re.Pattern[str]) -> set[str]:
    literals: set[str] = set()
    for path in PACKAGE.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and pattern.match(node.value)
            ):
                literals.add(node.value)
    return literals


def localization_catalogue() -> dict[str, Any]:
    """The fixture, built from the declarations rather than recorded."""
    return {
        "diagnostics": {
            code: spec.as_dict() for code, spec in sorted(DIAGNOSTIC_CATALOGUE.items())
        },
        "refusals": _refusal_codes(),
        "blockers": sorted(str(blocker) for blocker in Blocker),
        "locales": list(SUPPORTED_LOCALES),
    }


# ---------------------------------------------------------------------------
# The catalogue describes the source
# ---------------------------------------------------------------------------


def test_every_diagnostic_code_in_the_source_is_declared() -> None:
    assert _source_literals(DIAGNOSTIC_PREFIX) - set(DIAGNOSTIC_CATALOGUE) == set()


def test_every_declared_diagnostic_is_still_produced_somewhere() -> None:
    assert set(DIAGNOSTIC_CATALOGUE) - _source_literals(DIAGNOSTIC_PREFIX) == set()


def test_every_named_refusal_constant_is_published() -> None:
    published = set(_refusal_codes())
    for module in (labels, drafts, label_printing, label_batch):
        for name, value in vars(module).items():
            if name.startswith("CODE_"):
                assert value in published, f"{module.__name__}.{name}"


def test_the_contract_incompatibility_is_published() -> None:
    code = capability.IncompatibleLabelTemplateContract("missing", None).as_dict()
    assert code["code"] in _refusal_codes()


def test_library_errors_are_published_under_their_class_names() -> None:
    assert "label_template.TemplateNotFound" in _refusal_codes()
    assert "label_template.DraftVersionConflict" in _refusal_codes()


def test_every_catalogue_entry_is_well_formed() -> None:
    for code, spec in DIAGNOSTIC_CATALOGUE.items():
        assert spec.severities, code
        assert len(set(spec.parameters)) == len(spec.parameters), code
        assert all(re.fullmatch(r"[a-z_]+", name) for name in spec.parameters), code


# ---------------------------------------------------------------------------
# The guard in conftest.py
# ---------------------------------------------------------------------------


def _emit(code: str, **kwargs: Any) -> Diagnostic:
    """Build a diagnostic as though product code had."""
    namespace = {"Diagnostic": Diagnostic, "Layer": Layer, "Severity": Severity}
    exec(  # noqa: S102 -- a frame whose module name is the product's
        compile(
            "def build(code, **kwargs):\n    return Diagnostic(code=code, **kwargs)\n",
            "<product>",
            "exec",
        ),
        {**namespace, "__name__": "custom_components.growspace_manager.fake"},
        namespace,
    )
    return namespace["build"](code, **kwargs)  # type: ignore[operator]


def test_the_guard_refuses_an_undeclared_code() -> None:
    with pytest.raises(AssertionError, match="not in DIAGNOSTIC_CATALOGUE"):
        _emit(
            "raster.never_declared",
            severity=Severity.ERROR,
            layer=Layer.RASTER,
            message="",
        )


def test_the_guard_refuses_an_undeclared_parameter() -> None:
    with pytest.raises(AssertionError, match="undeclared"):
        _emit(
            "raster.missing",
            severity=Severity.ERROR,
            layer=Layer.RASTER,
            message="",
            parameters={"surprise": 1},
        )


def test_the_guard_refuses_the_wrong_layer_or_severity() -> None:
    with pytest.raises(AssertionError, match="emitted at"):
        _emit(
            "raster.missing", severity=Severity.ERROR, layer=Layer.DOCUMENT, message=""
        )
    with pytest.raises(AssertionError, match="emitted as"):
        _emit("raster.missing", severity=Severity.INFO, layer=Layer.RASTER, message="")


def test_a_diagnostic_a_test_spells_itself_is_not_the_product_s() -> None:
    Diagnostic(code="c", severity=Severity.INFO, layer=Layer.DOCUMENT, message="")


# ---------------------------------------------------------------------------
# The fixture the card translates against
# ---------------------------------------------------------------------------


def test_the_localization_fixture_is_exact(pytestconfig: pytest.Config) -> None:
    catalogue = localization_catalogue()
    if pytestconfig.getoption("regenerate_contract_fixture"):
        FIXTURE.write_text(
            f"{json.dumps(catalogue, indent=2, sort_keys=True)}\n", encoding="utf-8"
        )
    assert catalogue == json.loads(FIXTURE.read_text(encoding="utf-8"))
