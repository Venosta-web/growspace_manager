"""The representative subjects an editor previews a layout against.

Three families, in every print context: **typical** ordinary values, **long
content** bounded values built to exercise wrapping, fitting, ellipsis,
lineage length, canonical IDs, captions and QR density, and **missing optional
content** -- a valid subject with every optional value absent.

They are `SubjectFacts` like any record's, so they normalize through
`resolve_subject` and render through the same compiler and adapter a print
does. An editor comparing two layouts, and a test comparing two rasters, both
need the content to be the constant, which is why every value here is fixed
and why the catalogue version beside them moves when one changes.

`batch_item` shares the plant adapter's rules exactly, so its fixtures are the
plant ones in the batch context rather than a second set that could drift from
them.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
import hashlib

from .catalogue import PrintContext
from .content import (
    FIXTURE_CATALOGUE_VERSION,
    SUPPORTED_LOCALES,
    LabelAsset,
    LabelContentSnapshot,
    SubjectFacts,
    resolve_subject,
)

#: An 8x8 monochrome PNG: two diagonal strokes, enough to prove a logo element
#: reaches the raster and small enough to read as source. Written out rather
#: than committed as a file, so a fixture set stays one text diff.
_FIXTURE_LOGO_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAIAQAAAADsdIMmAAAAGElEQVR42m"
    "OoY7JnkmPiYWJg+sL0iFkBABRXAu3JXe0EAAAAAElFTkSuQmCC"
)

#: The immutable normalized asset a fixture's breeder logo resolves to. Built
#: from the bytes above so its hash is the bytes' own rather than a constant
#: beside them that could stop describing them.
FIXTURE_LOGO = LabelAsset(
    asset_id="growspace.fixture.logo.v1",
    content_hash=(
        "sha256:" + hashlib.sha256(base64.b64decode(_FIXTURE_LOGO_PNG)).hexdigest()
    ),
    media_type="image/png",
    data_uri=f"data:image/png;base64,{_FIXTURE_LOGO_PNG}",
    width=8,
    height=8,
)

#: The plant the plant and batch fixtures are of. A real UUID shape, because
#: the canonical ID's printed length is one of the things a long-content
#: preview has to show honestly.
_FIXTURE_PLANT_ID = "87b70561-96dd-4bcb-9153-6fc266b1d2dc"
_LONG_PLANT_ID = "0f3a9c21-7d4e-4b8a-9f16-2c5ed8b04a73"

_FIXTURE_ROUTE = "growspace/plant/{plant_id}"


def _links(plant_id: str) -> Mapping[str, str]:
    """Both QR forms of one fixture plant's route, as an adapter would build them."""
    route = _FIXTURE_ROUTE.format(plant_id=plant_id)
    return {
        "dashboard_url": f"http://homeassistant.local:8123/{route}",
        "home_assistant_app": f"homeassistant://navigate/{route}",
    }


@dataclass(frozen=True, slots=True)
class RepresentativeSubject:
    """A versioned fixture subject an editor can preview against."""

    id: str
    facts: SubjectFacts

    @property
    def context(self) -> PrintContext:
        """The print context this fixture stands for."""
        return self.facts.context

    def snapshot(
        self,
        *,
        as_of: datetime,
        locale: str = SUPPORTED_LOCALES[0],
        time_zone: str = "UTC",
    ) -> LabelContentSnapshot:
        """Take this fixture as a content snapshot for one instant."""
        return resolve_subject(
            replace(self.facts, subject=self.id),
            as_of=as_of,
            locale=locale,
            time_zone=time_zone,
            source=FIXTURE_CATALOGUE_VERSION,
        )


# ---------------------------------------------------------------------------
# Strain
# ---------------------------------------------------------------------------

#: The typical strain subject: ordinary values, nothing designed to stress
#: wrapping or truncation.
TYPICAL_STRAIN = RepresentativeSubject(
    id="growspace.fixture.strain.typical.v1",
    facts=SubjectFacts(
        context=PrintContext.STRAIN,
        subject="growspace.fixture.strain.typical.v1",
        strain_name="Blue Dream",
        phenotype_name="Pheno 3",
        breeder="Humboldt Seed Co.",
        lineage="Blueberry x Haze",
        logo=FIXTURE_LOGO,
        sources={"strain": "Blue Dream"},
    ),
)

#: Long content, bounded: a name that cannot fit on one line at the factory
#: size, a lineage that wraps, and a phenotype long enough to exercise its
#: caption. Nothing here is pathological -- the catalogue's input limits
#: refuse that before measurement -- it is the longest a real record gets.
LONG_STRAIN = RepresentativeSubject(
    id="growspace.fixture.strain.long.v1",
    facts=SubjectFacts(
        context=PrintContext.STRAIN,
        subject="growspace.fixture.strain.long.v1",
        strain_name="Grandmommy Purple Auto Remix",
        phenotype_name="Selection 14 (terpene-forward keeper)",
        breeder="Anesia Seeds International Genetics",
        lineage="Granddaddy Purple x Big Bud x Ruderalis Autoflower Line 7",
        logo=FIXTURE_LOGO,
        sources={"strain": "Grandmommy Purple Auto Remix"},
    ),
)

#: A valid subject with every optional value absent: the strain-library row
#: exists, it simply records nothing but the name.
SPARSE_STRAIN = RepresentativeSubject(
    id="growspace.fixture.strain.sparse.v1",
    facts=SubjectFacts(
        context=PrintContext.STRAIN,
        subject="growspace.fixture.strain.sparse.v1",
        strain_name="Northern Lights",
        phenotype_name="default",
        sources={"strain": "Northern Lights"},
    ),
)


# ---------------------------------------------------------------------------
# Plant, and the batch item that shares its rules
# ---------------------------------------------------------------------------

_TYPICAL_PLANT_FACTS = SubjectFacts(
    context=PrintContext.PLANT,
    subject="growspace.fixture.plant.typical.v1",
    strain_name="Blue Dream",
    phenotype_name="Pheno 3",
    breeder="Humboldt Seed Co.",
    lineage="Blueberry x Haze",
    logo=FIXTURE_LOGO,
    plant_id=_FIXTURE_PLANT_ID,
    stage="flower",
    stage_started_at="2026-09-02T09:15:00+00:00",
    links=_links(_FIXTURE_PLANT_ID),
    sources={"strain": "Blue Dream", "plant": _FIXTURE_PLANT_ID},
)

_LONG_PLANT_FACTS = SubjectFacts(
    context=PrintContext.PLANT,
    subject="growspace.fixture.plant.long.v1",
    strain_name="Grandmommy Purple Auto Remix",
    phenotype_name="Selection 14 (terpene-forward keeper)",
    breeder="Anesia Seeds International Genetics",
    lineage="Granddaddy Purple x Big Bud x Ruderalis Autoflower Line 7",
    logo=FIXTURE_LOGO,
    plant_id=_LONG_PLANT_ID,
    stage="flower_late",
    stage_started_at="2026-06-21T05:40:00+00:00",
    links=_links(_LONG_PLANT_ID),
    sources={"strain": "Grandmommy Purple Auto Remix", "plant": _LONG_PLANT_ID},
)

#: Every optional value absent, and the strain-library relationship missing
#: with them: the plant knows its own genetics, and nothing else resolved.
#: Its QR still does, because a plant always has a route.
_SPARSE_PLANT_FACTS = SubjectFacts(
    context=PrintContext.PLANT,
    subject="growspace.fixture.plant.sparse.v1",
    strain_name="Northern Lights",
    phenotype_name="default",
    library_linked=False,
    plant_id=_FIXTURE_PLANT_ID,
    stage="veg",
    stage_started_at=None,
    links=_links(_FIXTURE_PLANT_ID),
    sources={"plant": _FIXTURE_PLANT_ID},
)

TYPICAL_PLANT = RepresentativeSubject(
    id="growspace.fixture.plant.typical.v1", facts=_TYPICAL_PLANT_FACTS
)
LONG_PLANT = RepresentativeSubject(
    id="growspace.fixture.plant.long.v1", facts=_LONG_PLANT_FACTS
)
SPARSE_PLANT = RepresentativeSubject(
    id="growspace.fixture.plant.sparse.v1", facts=_SPARSE_PLANT_FACTS
)

TYPICAL_BATCH_ITEM = RepresentativeSubject(
    id="growspace.fixture.batch_item.typical.v1",
    facts=replace(_TYPICAL_PLANT_FACTS, context=PrintContext.BATCH_ITEM),
)
LONG_BATCH_ITEM = RepresentativeSubject(
    id="growspace.fixture.batch_item.long.v1",
    facts=replace(_LONG_PLANT_FACTS, context=PrintContext.BATCH_ITEM),
)
SPARSE_BATCH_ITEM = RepresentativeSubject(
    id="growspace.fixture.batch_item.sparse.v1",
    facts=replace(_SPARSE_PLANT_FACTS, context=PrintContext.BATCH_ITEM),
)


#: The three families, named so an editor can offer them without knowing what
#: is in them.
TYPICAL = "typical"
LONG_CONTENT = "long_content"
MISSING_OPTIONAL = "missing_optional"

#: Every fixture, by family and context. An editor switching context keeps the
#: family it was on rather than falling back to the first subject it finds.
REPRESENTATIVE_FAMILIES: Mapping[str, Mapping[PrintContext, RepresentativeSubject]] = {
    TYPICAL: {
        PrintContext.STRAIN: TYPICAL_STRAIN,
        PrintContext.PLANT: TYPICAL_PLANT,
        PrintContext.BATCH_ITEM: TYPICAL_BATCH_ITEM,
    },
    LONG_CONTENT: {
        PrintContext.STRAIN: LONG_STRAIN,
        PrintContext.PLANT: LONG_PLANT,
        PrintContext.BATCH_ITEM: LONG_BATCH_ITEM,
    },
    MISSING_OPTIONAL: {
        PrintContext.STRAIN: SPARSE_STRAIN,
        PrintContext.PLANT: SPARSE_PLANT,
        PrintContext.BATCH_ITEM: SPARSE_BATCH_ITEM,
    },
}

REPRESENTATIVE_SUBJECTS: Mapping[str, RepresentativeSubject] = {
    subject.id: subject
    for family in REPRESENTATIVE_FAMILIES.values()
    for subject in family.values()
}


def representative_subject(
    family: str, context: PrintContext
) -> RepresentativeSubject | None:
    """Return one family's fixture for one context, or nothing."""
    return REPRESENTATIVE_FAMILIES.get(family, {}).get(context)
