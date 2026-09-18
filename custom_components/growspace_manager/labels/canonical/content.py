"""The [[Label Content Snapshot]]: what one subject says, resolved once.

A snapshot is taken before rendering and never re-resolved. Preview, print,
every item of a batch and every retry of any of them read the same immutable
values, which is the only way a retry can reprint what the operator approved
rather than what the record says now.

Formatting is backend-owned. A document selects a closed presentation or date
style; it never supplies a caption, a format string or a prefix, so captions
and date shapes cannot drift between the preview and the paper, nor between
one installation and another.

This module carries the seam and the **representative** subjects an editor
previews against. Resolving a real strain, plant or batch item is the content
contract's own work and lands with the complete V1 snapshot; until then a
caller supplies values explicitly or asks for a versioned fixture, and both
travel this one path so neither can acquire behaviour the other lacks.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from .canonicalization import digest
from .catalogue import BINDING_CATALOGUE, MissingPolicy, PrintContext

#: Bumped when a fixture's values change, so a raster cached against the old
#: ones stops matching.
FIXTURE_CATALOGUE_VERSION = "growspace.label-fixtures.v1"

#: The one place a caption's words live. English only, as the compatibility
#: contract fixes for v1.
_CAPTIONS: Mapping[str, str] = {
    "strain.breeder": "Breeder",
    "strain.lineage": "Lineage",
    "plant.stage_started_on": "Started",
    "plant.id": "ID",
    "strain.phenotype": "Phenotype",
}

#: The closed date shapes, spelled once so a preview and a print agree.
_DATE_FORMATS: Mapping[str, str] = {
    "short": "%Y-%m-%d",
    "medium": "%d %b %Y",
    "long": "%d %B %Y",
}


@dataclass(frozen=True, slots=True)
class LabelContentSnapshot:
    """One immutable resolution of every binding for one subject.

    `values` maps binding ID to the normalized value behind it. A binding
    absent from the mapping is *absent for this subject*, and its catalogue
    entry's missing policy decides what that means. A binding present with an
    empty string is treated as absent: an empty printable value is a formatter
    defect, not a policy.
    """

    context: PrintContext
    subject: str
    as_of: datetime
    values: Mapping[str, str] = field(default_factory=dict)
    locale: str = "en"
    time_zone: str = "UTC"
    #: Where the values came from, so a raster of a fixture cannot be cached
    #: as though it were a raster of a record.
    source: str = "caller"

    def supports(self, binding_id: str) -> bool:
        """Return whether this snapshot's context admits one binding at all."""
        definition = BINDING_CATALOGUE.get(binding_id)
        return definition is not None and self.context in definition.contexts

    def resolve(self, binding_id: str, parameters: Mapping[str, str]) -> str | None:
        """Return the printable string for one bound element, or nothing.

        `print.date` is derived from the captured instant rather than looked
        up, because the date a label was printed on is a property of the
        printing and never of the subject.
        """
        if binding_id == "print.date":
            style = parameters.get("date_style", "medium")
            return self.as_of.strftime(
                _DATE_FORMATS.get(style, _DATE_FORMATS["medium"])
            )

        value = self.values.get(binding_id)
        if not value:
            return None
        if parameters.get("presentation") == "labeled":
            caption = _CAPTIONS.get(binding_id)
            if caption:
                return f"{caption}: {value}"
        return value

    @property
    def identity(self) -> str:
        """The immutable identity a Render Context records for this snapshot."""
        return digest(
            {
                "context": str(self.context),
                "subject": self.subject,
                "locale": self.locale,
                "time_zone": self.time_zone,
                "as_of": self.as_of.isoformat(),
                "source": self.source,
                "values": dict(self.values),
            }
        )


def missing_policy(binding_id: str) -> MissingPolicy:
    """Return what the absence of one binding's value means."""
    definition = BINDING_CATALOGUE.get(binding_id)
    if definition is None:
        return MissingPolicy.BLOCK
    return definition.missing_policy


@dataclass(frozen=True, slots=True)
class RepresentativeSubject:
    """A versioned fixture subject an editor can preview against.

    Deterministic on purpose: an editor comparing two layouts, and a test
    comparing two rasters, both need the content to be the constant.
    """

    id: str
    context: PrintContext
    values: Mapping[str, str] = field(default_factory=dict)

    def snapshot(self, *, as_of: datetime) -> LabelContentSnapshot:
        """Take this fixture as a content snapshot for one instant."""
        return LabelContentSnapshot(
            context=self.context,
            subject=self.id,
            as_of=as_of,
            values=dict(self.values),
            source=FIXTURE_CATALOGUE_VERSION,
        )


#: The typical strain subject: ordinary values, nothing designed to stress
#: wrapping or truncation. The long-content and missing-optional fixtures the
#: content contract also requires arrive with the complete snapshot work.
TYPICAL_STRAIN = RepresentativeSubject(
    id="growspace.fixture.strain.typical.v1",
    context=PrintContext.STRAIN,
    values={
        "strain.name": "Blue Dream",
        "strain.phenotype": "Pheno 3",
        "strain.breeder": "Humboldt Seed Co.",
        "strain.lineage": "Blueberry x Haze",
    },
)

REPRESENTATIVE_SUBJECTS: Mapping[str, RepresentativeSubject] = {
    TYPICAL_STRAIN.id: TYPICAL_STRAIN,
}
