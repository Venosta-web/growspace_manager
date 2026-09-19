"""The [[Label Content Snapshot]]: what one subject says, resolved once.

A snapshot is taken before rendering and never re-resolved. Preview, print,
every item of a batch and every retry of any of them read the same immutable
values, which is the only way a retry can reprint what the operator approved
rather than what the record says now. Nothing here reaches back into a plant,
a strain row, a logo file, the clock or the Home Assistant URL configuration:
a [[Source Adapter]] reads all of that once, and what it captured is what
prints.

Formatting is backend-owned. A document selects a closed presentation or date
style; it never supplies a caption, a format string or a prefix, so captions
and date shapes cannot drift between the preview and the paper, nor between
one installation and another.

This module owns two things: the immutable snapshot and its formatter, and
`resolve_subject` -- the one normalizer every context goes through. Every rule
about which sentinel means absence, which absence is a missing value and which
is a broken source relationship, which date a stage carries and what a future
one does, is applied here and nowhere else.

Reading one record out of integration state is `subjects.py`'s work; the
representative subjects an editor previews against are `fixtures.py`'s, and
they are `SubjectFacts` like any record's so that they come through this same
formatter rather than through example strings maintained beside it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import Any

from custom_components.growspace_manager.domain.date_logic import parse_date_field
from custom_components.growspace_manager.domain.stage import (
    STAGE_REGISTRY,
    PlantStage,
    get_stage_definition,
)
from homeassistant.exceptions import HomeAssistantError

from .canonicalization import digest
from .catalogue import (
    BINDING_CATALOGUE,
    DATE_STYLES,
    QR_TARGETS,
    MissingPolicy,
    PrintContext,
)
from .diagnostics import Diagnostic, Layer, Severity

#: Bumped when a fixture's values change, so a raster cached against the old
#: ones stops matching.
FIXTURE_CATALOGUE_VERSION = "growspace.label-fixtures.v2"

#: The one place a caption's words live. English only, as the compatibility
#: contract fixes for v1.
_CAPTIONS: Mapping[str, str] = {
    "strain.breeder": "Breeder",
    "strain.lineage": "Lineage",
    "plant.stage_started_on": "Started",
    "plant.id": "ID",
    "strain.phenotype": "Phenotype",
}

#: The print locales this product claims, spelled out rather than accepted
#: from whatever a browser sends. V1's product language is English; a regional
#: variant shares the reviewed English captions, stage names and plurals and
#: differs only in civil date order.
SUPPORTED_LOCALES: tuple[str, ...] = (
    "en",
    "en-AU",
    "en-GB",
    "en-IE",
    "en-NZ",
    "en-US",
)

#: The one supported locale whose civil date order is month-first.
_MONTH_FIRST = frozenset({"en-US"})

_MONTH_ABBREVIATIONS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)

#: What the card and the strain library both write to mean "nothing recorded".
#: None of them may reach the label as literal text.
_EMPTY_VALUES = frozenset({"-", "–", "—"})

#: The phenotype name a strain with no named phenotype carries.
_DEFAULT_PHENOTYPE = "default"

#: Sub-stages the registry does not define a start field for. A plant in one
#: of these entered its parent stage, and that is the date a label carries.
PARENT_STAGES: Mapping[str, PlantStage] = {
    PlantStage.VEG_EARLY: PlantStage.VEG,
    PlantStage.VEG_LATE: PlantStage.VEG,
    PlantStage.FLOWER_EARLY: PlantStage.FLOWER,
    PlantStage.FLOWER_MID: PlantStage.FLOWER,
    PlantStage.FLOWER_LATE: PlantStage.FLOWER,
}

#: What separates the stage from its age in the compact composite form.
_AGE_SEPARATOR = " · "

_BREEDER_BINDING = "strain.breeder"
_LINEAGE_BINDING = "strain.lineage"
_LOGO_BINDING = "strain.breeder.logo"
_LINK_BINDING = "plant.link"
_STAGE_DATE_BINDING = "plant.stage_started_on"
_STAGE_AGE_BINDING = "plant.stage_and_age"


class UnsupportedLocaleError(HomeAssistantError):
    """Raised when a request names a locale this product cannot print in.

    Explicit rather than a fallback: silently printing English captions under
    a locale the caller believes is German is the failure this refuses.
    """


def resolve_locale(requested: str | None) -> str:
    """Return the supported locale one request resolves to, or refuse.

    Matching is case-insensitive on the region subtag so `en-gb` from a
    browser resolves to the catalogue's `en-GB`; the resolved spelling is what
    the snapshot records, because that is what the formatter reads.
    """
    if not requested:
        return SUPPORTED_LOCALES[0]
    folded = requested.strip().casefold()
    for supported in SUPPORTED_LOCALES:
        if supported.casefold() == folded:
            return supported
    raise UnsupportedLocaleError(
        f"{requested!r} is not a supported print locale "
        f"({', '.join(SUPPORTED_LOCALES)})"
    )


@dataclass(frozen=True, slots=True)
class LabelAsset:
    """One immutable normalized image a snapshot carries by value.

    By value rather than by path: a breeder who replaces their logo tomorrow
    must not change what a label printed today reprints on retry. The bytes
    travel with the snapshot and the hash is their identity.
    """

    asset_id: str
    content_hash: str
    media_type: str
    #: The normalized image, as the `data:` URI the renderer consumes.
    data_uri: str
    width: int
    height: int

    def as_identity(self) -> dict[str, Any]:
        """Return the part of this asset a snapshot identity is taken over.

        The hash stands for the bytes, so the data URI itself stays out of the
        digest -- it would make every identity as long as its largest logo
        without distinguishing one more pair of snapshots.
        """
        return {
            "asset_id": self.asset_id,
            "content_hash": self.content_hash,
            "media_type": self.media_type,
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True, slots=True)
class ContentAbsence:
    """Why one binding has no value for this subject.

    The missing policy says what absence *does*; this says what happened, so
    "the strain library has no row for this plant's strain" and "that strain
    has no breeder" do not arrive as the same warning.
    """

    code: str
    severity: Severity
    parameters: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SubjectFacts:
    """What one [[Source Adapter]] read, before any normalization.

    Deliberately dumb: raw strings as the store holds them, the captured
    lifecycle timestamp as it was written, and whether the strain-library
    relationship resolved at all. Every rule about blanks, sentinels, dates,
    ages and captions is applied once by `resolve_subject`, so an adapter
    cannot acquire a formatting opinion of its own.
    """

    context: PrintContext
    #: The identity this snapshot is of, for logs and diagnostics.
    subject: str
    strain_name: str | None = None
    phenotype_name: str | None = None
    breeder: str | None = None
    lineage: str | None = None
    logo: LabelAsset | None = None
    #: Why there is no usable logo, where there is a breeder but no image.
    logo_absence: ContentAbsence | None = None
    #: Whether the saved strain this subject names was found at all.
    library_linked: bool = True
    plant_id: str | None = None
    #: The plant's current stage, sub-stages included.
    stage: str | None = None
    #: The [[Lifecycle Timestamp]] of that stage, exactly as stored.
    stage_started_at: str | None = None
    #: QR target name to the URI it resolved to.
    links: Mapping[str, str] = field(default_factory=dict)
    #: Why a selected target has no URI.
    link_absence: ContentAbsence | None = None
    #: Where the values came from, as far as this installation can say.
    sources: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LabelContentSnapshot:
    """One immutable resolution of every binding for one subject.

    `values` maps binding ID to the normalized printable value behind it. A
    binding absent from the mapping is *absent for this subject*, and its
    catalogue entry's missing policy decides what that means -- while its
    entry in `absences`, where there is one, decides what the diagnostic says.
    A binding present with an empty string is treated as absent: an empty
    printable value is a formatter defect, not a policy.

    `diagnostics` are the record-level ones resolution itself produced. They
    belong to the subject rather than to any element, so they are reported
    even by a layout that binds nothing to the value they concern.
    """

    context: PrintContext
    subject: str
    as_of: datetime
    values: Mapping[str, str] = field(default_factory=dict)
    #: Binding ID to the immutable image captured for it.
    assets: Mapping[str, LabelAsset] = field(default_factory=dict)
    #: QR target name to the URI captured for it.
    links: Mapping[str, str] = field(default_factory=dict)
    #: Binding ID to why it has no value.
    absences: Mapping[str, ContentAbsence] = field(default_factory=dict)
    #: What resolution found wrong with the record itself.
    diagnostics: tuple[Diagnostic, ...] = ()
    #: Provenance, as far as this installation can state it.
    sources: Mapping[str, str] = field(default_factory=dict)
    locale: str = "en"
    time_zone: str = "UTC"
    #: Where the values came from, so a raster of a fixture cannot be cached
    #: as though it were a raster of a record.
    source: str = "caller"

    def supports(self, binding_id: str) -> bool:
        """Return whether this snapshot's context admits one binding at all."""
        definition = BINDING_CATALOGUE.get(binding_id)
        return definition is not None and self.context in definition.contexts

    def absence(self, binding_id: str) -> ContentAbsence | None:
        """Return why one binding has no value here, where resolution knows."""
        return self.absences.get(binding_id)

    def resolve(self, binding_id: str, parameters: Mapping[str, str]) -> str | None:
        """Return the printable string for one bound element, or nothing.

        `print.date` is derived from the captured instant rather than looked
        up, because the date a label was printed on is a property of the
        printing and never of the subject.
        """
        if binding_id == "print.date":
            return format_date(self.as_of.date(), _style(parameters), self.locale)
        if binding_id == _LINK_BINDING:
            return self.links.get(parameters.get("target", QR_TARGETS[0])) or None
        if binding_id in self.assets:
            return self.assets[binding_id].data_uri or None

        value = self.values.get(binding_id)
        if not value:
            return None
        if binding_id == _STAGE_DATE_BINDING:
            started = date.fromisoformat(value)
            value = format_date(started, _style(parameters), self.locale)
        if parameters.get("presentation") == "labeled":
            caption = _CAPTIONS.get(binding_id)
            if caption:
                return f"{caption}: {value}"
        return value

    @property
    def identity(self) -> str:
        """The immutable identity a Render Context records for this snapshot.

        Every captured input is in it and nothing derived is: two snapshots
        sharing this identity resolve every binding identically, and a
        diagnostic is a consequence of the inputs rather than one of them.
        """
        return digest(
            {
                "context": str(self.context),
                "subject": self.subject,
                "locale": self.locale,
                "time_zone": self.time_zone,
                "as_of": self.as_of.isoformat(),
                "source": self.source,
                "values": dict(self.values),
                "assets": {
                    binding: asset.as_identity()
                    for binding, asset in self.assets.items()
                },
                "links": dict(self.links),
                "absences": {
                    binding: {
                        "code": item.code,
                        "severity": str(item.severity),
                    }
                    for binding, item in self.absences.items()
                },
                "sources": dict(self.sources),
            }
        )


def missing_policy(binding_id: str) -> MissingPolicy:
    """Return what the absence of one binding's value means."""
    definition = BINDING_CATALOGUE.get(binding_id)
    if definition is None:
        return MissingPolicy.BLOCK
    return definition.missing_policy


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def _style(parameters: Mapping[str, str]) -> str:
    """Return the requested date style, or the catalogue's default."""
    style = parameters.get("date_style", DATE_STYLES[0])
    return style if style in DATE_STYLES else DATE_STYLES[0]


def format_date(value: date, style: str, locale: str) -> str:
    """Render one calendar date in one supported locale's civil order.

    Written out rather than handed to `strftime`: the no-padding directives a
    civil short date needs are platform-specific, and a label that printed
    `09/2026` on one host and `9/2026` on another would be a fidelity bug
    nobody could reproduce.
    """
    if style == "iso":
        return value.isoformat()
    month = _MONTH_ABBREVIATIONS[value.month - 1]
    if style == "medium":
        if locale in _MONTH_FIRST:
            return f"{month} {value.day}, {value.year}"
        return f"{value.day} {month} {value.year}"
    if locale in _MONTH_FIRST:
        return f"{value.month}/{value.day}/{value.year}"
    return f"{value.day:02d}/{value.month:02d}/{value.year}"


def stage_display_name(stage: str | None) -> str | None:
    """Return the printable name of one plant stage, sub-stages collapsed."""
    if not stage:
        return None
    definition = get_stage_definition(stage)
    if definition is None:
        parent = PARENT_STAGES.get(stage)
        definition = STAGE_REGISTRY.get(parent) if parent else None
    return definition.display_name if definition else None


def format_age(stage_name: str, days: int) -> str:
    """Return the localized compact stage-and-age composite.

    Day zero is a real answer -- a plant flipped this morning is `0 days` into
    flower -- so the singular applies to one day only.
    """
    unit = "day" if days == 1 else "days"
    return f"{stage_name}{_AGE_SEPARATOR}{days} {unit}"


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def normalize_value(value: str | None) -> str | None:
    """Return one stored string as printable text, or nothing.

    Blank, whitespace-only and the stores' own "nothing recorded" sentinels
    all mean the same thing, and none of them may reach paper as literal text.
    """
    if value is None:
        return None
    stripped = value.strip()
    if not stripped or stripped in _EMPTY_VALUES:
        return None
    return stripped


def resolve_subject(
    facts: SubjectFacts,
    *,
    as_of: datetime,
    locale: str = SUPPORTED_LOCALES[0],
    time_zone: str = "UTC",
    source: str = "caller",
) -> LabelContentSnapshot:
    """Normalize one subject's captured facts into an immutable snapshot.

    The single owner of every content rule in the v1 catalogue: which sentinel
    means absence, which absence is a missing value and which is a broken
    source relationship, which date a stage carries and what a future one
    does. A Source Adapter reads; this decides.

    `as_of` is expected in the captured time zone already, so the printed
    date, the stage date and the age are all read off one calendar and a batch
    crossing local midnight cannot disagree with itself.
    """
    values: dict[str, str] = {}
    absences: dict[str, ContentAbsence] = {}
    diagnostics: list[Diagnostic] = []
    assets: dict[str, LabelAsset] = {}

    _resolve_strain(facts, values, absences, diagnostics)
    _resolve_library(facts, values, absences, assets)
    _resolve_plant(facts, values, absences, diagnostics, as_of)

    return LabelContentSnapshot(
        context=facts.context,
        subject=facts.subject,
        as_of=as_of,
        values=values,
        assets=assets,
        links=dict(facts.links),
        absences=absences,
        diagnostics=tuple(diagnostics),
        sources=dict(facts.sources),
        locale=locale,
        time_zone=time_zone,
        source=source,
    )


def _resolve_strain(
    facts: SubjectFacts,
    values: dict[str, str],
    absences: dict[str, ContentAbsence],
    diagnostics: list[Diagnostic],
) -> None:
    """Resolve the two values a subject carries in its own right.

    A plant's own strain and phenotype names remain the authority for its
    identity even when the library relationship is missing, which is why
    neither reads the library at all.
    """
    name = normalize_value(facts.strain_name)
    if name:
        values["strain.name"] = name
    else:
        diagnostics.append(
            Diagnostic(
                code="content.missing_required",
                severity=Severity.ERROR,
                layer=Layer.CONTENT,
                message=f"{facts.subject} has no strain name, so it cannot print.",
                parameters={"binding": "strain.name", "subject": facts.subject},
            )
        )

    phenotype = normalize_value(facts.phenotype_name)
    if phenotype and phenotype.casefold() != _DEFAULT_PHENOTYPE:
        values["strain.phenotype"] = phenotype
    else:
        absences["strain.phenotype"] = ContentAbsence(
            code="content.missing_optional",
            severity=Severity.WARNING,
            parameters={"binding": "strain.phenotype"},
        )


def _resolve_library(
    facts: SubjectFacts,
    values: dict[str, str],
    absences: dict[str, ContentAbsence],
    assets: dict[str, LabelAsset],
) -> None:
    """Resolve the three values that come only from the saved strain row.

    Breeder, lineage and the dynamic logo have one source each and no fallback
    chain. Where the relationship itself did not resolve, all three say so
    with the same distinct code, because "this strain is not in the library"
    and "this strain has no breeder" want different corrections.
    """
    unresolved = ContentAbsence(
        code="content.source_unresolved",
        severity=Severity.WARNING,
        parameters={"strain": facts.strain_name or ""},
    )

    for binding, raw in (
        (_BREEDER_BINDING, facts.breeder),
        (_LINEAGE_BINDING, facts.lineage),
    ):
        value = normalize_value(raw)
        if value:
            values[binding] = value
        elif facts.library_linked:
            absences[binding] = ContentAbsence(
                code="content.missing_optional",
                severity=Severity.WARNING,
                parameters={"binding": binding},
            )
        else:
            absences[binding] = replace(
                unresolved, parameters={**unresolved.parameters, "binding": binding}
            )

    if facts.logo is not None:
        assets[_LOGO_BINDING] = facts.logo
    elif facts.logo_absence is not None:
        absences[_LOGO_BINDING] = facts.logo_absence
    elif facts.library_linked:
        absences[_LOGO_BINDING] = ContentAbsence(
            code="content.missing_optional",
            severity=Severity.WARNING,
            parameters={"binding": _LOGO_BINDING},
        )
    else:
        absences[_LOGO_BINDING] = replace(
            unresolved, parameters={**unresolved.parameters, "binding": _LOGO_BINDING}
        )


def _resolve_plant(
    facts: SubjectFacts,
    values: dict[str, str],
    absences: dict[str, ContentAbsence],
    diagnostics: list[Diagnostic],
    as_of: datetime,
) -> None:
    """Resolve the four values only a plant subject has.

    The stage date is the one belonging to the captured *current* stage and
    nothing else: never an earlier populated lifecycle field, never the
    creation time, never the latest non-empty one. A plant that has flipped
    but whose `flower_start` is empty has no stage date, and saying so is the
    point -- silently printing its `veg_start` would date the label to a stage
    it has left.
    """
    if facts.context is PrintContext.STRAIN:
        return

    if facts.plant_id:
        values["plant.id"] = facts.plant_id

    if facts.link_absence is not None:
        absences[_LINK_BINDING] = facts.link_absence
    elif not facts.links:
        absences[_LINK_BINDING] = ContentAbsence(
            code="content.qr_target_unavailable",
            severity=Severity.ERROR,
            parameters={"binding": _LINK_BINDING},
        )

    stage_name = stage_display_name(facts.stage)
    started = parse_date_field(facts.stage_started_at)
    started_on = started.astimezone(as_of.tzinfo).date() if started else None

    if started_on is None or stage_name is None:
        missing = ContentAbsence(
            code="content.stage_date_missing",
            severity=Severity.WARNING,
            parameters={"stage": facts.stage or ""},
        )
        absences[_STAGE_DATE_BINDING] = replace(
            missing, parameters={**missing.parameters, "binding": _STAGE_DATE_BINDING}
        )
        absences[_STAGE_AGE_BINDING] = replace(
            missing, parameters={**missing.parameters, "binding": _STAGE_AGE_BINDING}
        )
        return

    today = as_of.date()
    if started_on > today:
        _refuse_future_stage_date(facts, absences, diagnostics, started_on, today)
        return

    values[_STAGE_DATE_BINDING] = started_on.isoformat()
    values[_STAGE_AGE_BINDING] = format_age(stage_name, (today - started_on).days)


def _refuse_future_stage_date(
    facts: SubjectFacts,
    absences: dict[str, ContentAbsence],
    diagnostics: list[Diagnostic],
    started_on: date,
    today: date,
) -> None:
    """Block one record whose current stage claims to have begun tomorrow.

    An age cannot be negative and a start date cannot be in the future, so
    this is a record whose lifecycle data is wrong rather than a label whose
    optional line is empty. It is reported against the record as well as
    against every element that asked, because a layout binding neither would
    otherwise print a plausible label for an impossible plant.
    """
    parameters = {
        "stage": facts.stage or "",
        "started_on": started_on.isoformat(),
        "as_of": today.isoformat(),
    }
    diagnostics.append(
        Diagnostic(
            code="content.stage_date_in_future",
            severity=Severity.ERROR,
            layer=Layer.CONTENT,
            message=(
                f"{facts.subject} entered {facts.stage} on {started_on.isoformat()}, "
                f"after the {today.isoformat()} this label is being printed on."
            ),
            parameters={**parameters, "subject": facts.subject},
        )
    )
    for binding in (_STAGE_DATE_BINDING, _STAGE_AGE_BINDING):
        absences[binding] = ContentAbsence(
            code="content.stage_date_in_future",
            severity=Severity.ERROR,
            parameters={**parameters, "binding": binding},
        )
