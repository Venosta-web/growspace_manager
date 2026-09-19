"""The backend-owned catalogues a Label Layout may reference.

Label Sizes, Style Tokens and Content Bindings are all the same kind of thing:
a versioned identity the integration defines and a saved document may only
point at. None of them is a name the card invents, a CSS value, a font path or
an expression. A token that changes meaning gets a new version rather than a
new definition, which is what keeps an old Template Revision printing what it
printed.

Only the identities are here. What a binding resolves to for one subject is
[[Label Content Snapshot]] work; how a token becomes pixels is the compiler's.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

#: Bumped when any catalogue below gains, loses or redefines an entry. The
#: capability response carries it so an editor can invalidate stale choices.
CAPABILITY_GENERATION = 2

LABEL_SIZE_CATALOGUE_VERSION = "growspace.label-sizes.v1"
STYLE_TOKEN_CATALOGUE_VERSION = "growspace.label-style-tokens.v1"
BINDING_CATALOGUE_VERSION = "growspace.label-bindings.v1"


@dataclass(frozen=True, slots=True)
class LabelSize:
    """One physical stock identity, in millimetres.

    The versioned ID is the identity; `classic_key` is the same stock spelled
    the way the pre-template request spells it, and exists only so the
    Compatibility Adapter can name a size both paths agree on.
    """

    id: str
    width_mm: float
    height_mm: float
    classic_key: str


LABEL_SIZES: Mapping[str, LabelSize] = {
    size.id: size
    for size in (
        LabelSize("growspace.stock.50x30.v1", 50.0, 30.0, "50x30"),
        LabelSize("growspace.stock.40x30.v1", 40.0, 30.0, "40x30"),
        LabelSize("growspace.stock.50x50.v1", 50.0, 50.0, "50x50"),
        LabelSize("growspace.stock.50x80.v1", 50.0, 80.0, "50x80"),
        LabelSize("growspace.stock.50x15.v1", 50.0, 15.0, "50x15"),
    )
}


@dataclass(frozen=True, slots=True)
class FontToken:
    """A printable font face, resolved to a file the render environment holds.

    Weight and face live in the token rather than in the document so the
    selected file is deterministic. Size stays geometry, because exact
    millimetre control is part of the accepted editor.
    """

    id: str
    file: str
    description: str


#: The two faces the render environment ships. A document naming anything else
#: is rejected rather than silently substituted with a similar one.
FONT_TOKENS: Mapping[str, FontToken] = {
    token.id: token
    for token in (
        FontToken("growspace.sans.bold.v1", "ppb.ttf", "Bold sans, for headings"),
        FontToken("growspace.sans.regular.v1", "rbm.ttf", "Regular sans, for body"),
    )
}


@dataclass(frozen=True, slots=True)
class LineSpacingToken:
    """Leading, as a fraction of the resolved font size.

    A fraction rather than a millimetre value because leading that did not
    follow an auto-fitted font size would open gaps exactly when shrinking has
    made the text tightest.
    """

    id: str
    ratio: float


LINE_SPACING_TOKENS: Mapping[str, LineSpacingToken] = {
    token.id: token
    for token in (
        LineSpacingToken("growspace.spacing.compact.v1", 0.05),
        LineSpacingToken("growspace.spacing.normal.v1", 0.20),
        LineSpacingToken("growspace.spacing.relaxed.v1", 0.40),
    )
}


@dataclass(frozen=True, slots=True)
class MonochromeToken:
    """How a colour or grey image becomes the one ink this printer has."""

    id: str
    dither: bool


MONOCHROME_TOKENS: Mapping[str, MonochromeToken] = {
    token.id: token
    for token in (
        MonochromeToken("growspace.mono.threshold.v1", dither=False),
        MonochromeToken("growspace.mono.dither.v1", dither=True),
    )
}


class ErrorCorrection(StrEnum):
    """QR error-correction level, named rather than spelled as a letter."""

    LOW = "low"
    MEDIUM = "medium"
    QUARTILE = "quartile"
    HIGH = "high"


class ElementKind(StrEnum):
    """The four element variants version 1 has."""

    TEXT = "text"
    LOGO = "logo"
    QR = "qr"
    DIVIDER = "divider"


class PrintContext(StrEnum):
    """What a label is being printed about."""

    STRAIN = "strain"
    PLANT = "plant"
    BATCH_ITEM = "batch_item"


class MissingPolicy(StrEnum):
    """What the absence of a binding's value does."""

    #: The template cannot publish and no subject can print without it.
    BLOCK = "block"
    #: No ink, the frame preserved, and a warning naming the element.
    WARN_AND_OMIT = "warn_and_omit"
    #: The value cannot be absent; absence is a defect, not a policy.
    NEVER_ABSENT = "never_absent"


_ALL_CONTEXTS = (PrintContext.STRAIN, PrintContext.PLANT, PrintContext.BATCH_ITEM)
_PLANT_CONTEXTS = (PrintContext.PLANT, PrintContext.BATCH_ITEM)

#: The closed set of presentation choices a captioned text binding accepts.
PRESENTATIONS = ("value", "labeled")

#: The closed set of date styles a date binding accepts. `short` and
#: `medium` follow the captured locale; `iso` is `YYYY-MM-DD` whatever the
#: locale, which is what makes it the one shape a scanner or a spreadsheet
#: can rely on.
DATE_STYLES = ("short", "medium", "iso")

#: The closed set of QR targets `plant.link` accepts. Both name the same
#: configured plant route; they differ only in the URI form that reaches it.
QR_TARGETS = ("dashboard_url", "home_assistant_app")


@dataclass(frozen=True, slots=True)
class BindingDefinition:
    """One catalogue entry: what a binding is for, and what it does when empty.

    `parameters` maps each accepted parameter name to its closed value set,
    and its first entry is that parameter's default. A parameter absent from
    this mapping is an error rather than an invitation to pass it through.
    """

    id: str
    kinds: tuple[ElementKind, ...]
    contexts: tuple[PrintContext, ...]
    parameters: Mapping[str, tuple[str, ...]]
    missing_policy: MissingPolicy
    #: Whether a publishable Template Revision must contain this binding.
    required: bool = False


BINDING_CATALOGUE: Mapping[str, BindingDefinition] = {
    binding.id: binding
    for binding in (
        BindingDefinition(
            "strain.name",
            (ElementKind.TEXT,),
            _ALL_CONTEXTS,
            {},
            MissingPolicy.BLOCK,
            required=True,
        ),
        BindingDefinition(
            "strain.phenotype",
            (ElementKind.TEXT,),
            _ALL_CONTEXTS,
            {"presentation": PRESENTATIONS},
            MissingPolicy.WARN_AND_OMIT,
        ),
        BindingDefinition(
            "strain.breeder",
            (ElementKind.TEXT,),
            _ALL_CONTEXTS,
            {"presentation": ("labeled", "value")},
            MissingPolicy.WARN_AND_OMIT,
        ),
        BindingDefinition(
            "strain.lineage",
            (ElementKind.TEXT,),
            _ALL_CONTEXTS,
            {"presentation": ("labeled", "value")},
            MissingPolicy.WARN_AND_OMIT,
        ),
        BindingDefinition(
            "plant.stage_started_on",
            (ElementKind.TEXT,),
            _PLANT_CONTEXTS,
            {"presentation": ("labeled", "value"), "date_style": DATE_STYLES},
            MissingPolicy.WARN_AND_OMIT,
        ),
        BindingDefinition(
            "plant.stage_and_age",
            (ElementKind.TEXT,),
            _PLANT_CONTEXTS,
            {},
            MissingPolicy.WARN_AND_OMIT,
        ),
        BindingDefinition(
            "plant.id",
            (ElementKind.TEXT,),
            _PLANT_CONTEXTS,
            {"presentation": ("labeled", "value")},
            MissingPolicy.BLOCK,
        ),
        BindingDefinition(
            "strain.breeder.logo",
            (ElementKind.LOGO,),
            _ALL_CONTEXTS,
            {},
            MissingPolicy.WARN_AND_OMIT,
        ),
        BindingDefinition(
            "plant.link",
            (ElementKind.QR,),
            _PLANT_CONTEXTS,
            {"target": QR_TARGETS},
            MissingPolicy.BLOCK,
        ),
        BindingDefinition(
            "print.date",
            (ElementKind.TEXT,),
            _ALL_CONTEXTS,
            {"date_style": DATE_STYLES},
            MissingPolicy.NEVER_ABSENT,
        ),
    )
}

#: The binding a publishable Template Revision must carry on a text element.
REQUIRED_BINDING = "strain.name"
