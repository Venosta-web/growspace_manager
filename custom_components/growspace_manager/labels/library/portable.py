"""The portable bundle: sharing a label design, not moving a library.

A bundle is what an administrator sends somebody else, or carries between two
installations that have nothing else in common. It holds **current revisions
and nothing more**: the design, its identity, the stock it is for, the
structural provenance of where it came from, and a list of everything it
depends on. It deliberately does not hold history, drafts, defaults,
tombstones, Factory Template definitions, the Library Generation, or any Home
Assistant user ID -- none of those mean anything on the other installation, and
a share that quietly carried somebody's unpublished work or re-pointed their
defaults would be a restore wearing a share's name. Moving a library whole is
what a backup is for.

Three rules the shape is built around.

**Nothing is interpreted before it is verified.** A bundle carries a checksum
over everything else in it, and reading one checks the format version, the
structure and that checksum before any template in it is looked at. Structural
damage and a wrong digest are the same refusal, because both mean these bytes
are not a bundle this integration can vouch for -- and neither is a reason to
import the entries that happen to parse.

**A newer bundle is an upgrade, not a partial import.** An unknown format
version fails preflight and names the version that reads it. There is one
format today; `migrate` is the single seam an older one would be lifted through,
so a future version has one place to add a step and no place to add a guess.

**Dependencies are named, never dropped.** Every binding, font, spacing,
monochrome and asset the document refers to is written into the entry beside
it, and an import refuses on any of them the installation does not have. That
is the difference between "this label needs something you do not have" and a
label that silently prints without its lineage line.

The entry's `digest` is the normalized layout digest, which is what makes
importing the same bundle twice a no-op rather than a second copy: same
identity and same digest is the template already being here.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..canonical import (
    BINDING_CATALOGUE,
    BINDING_CATALOGUE_VERSION,
    FONT_TOKENS,
    LABEL_SIZE_CATALOGUE_VERSION,
    LABEL_SIZES,
    LINE_SPACING_TOKENS,
    MONOCHROME_TOKENS,
    SCHEMA,
    STYLE_TOKEN_CATALOGUE_VERSION,
    VERSION,
    digest,
)
from .errors import BundleNotReadable, IncompatibleBundle
from .records import NamedTemplate, Provenance

#: The bundle document's own identity, beside its version, so a stray file can
#: be recognised for what it is -- and told apart from a backup, which is a
#: different document with a different promise.
BUNDLE_SCHEMA = "growspace.label-template-bundle"

#: The bundle format this integration writes and reads.
BUNDLE_VERSION = 1

#: The dependency kinds an entry lists, and the installed catalogue each one is
#: checked against. Assets are absent on purpose: an asset is resolved per
#: subject at render time and there is no installed catalogue of them, so one
#: is recorded to be seen rather than verified, and the content layer reports a
#: missing logo the way it reports any other absent content.
_CATALOGUES: Mapping[str, Mapping[str, Any]] = {
    "label_sizes": LABEL_SIZES,
    "bindings": BINDING_CATALOGUE,
    "fonts": FONT_TOKENS,
    "line_spacings": LINE_SPACING_TOKENS,
    "monochromes": MONOCHROME_TOKENS,
}

#: Every dependency kind an entry carries, verifiable or not.
DEPENDENCY_KINDS = (*_CATALOGUES, "assets")


@dataclass(frozen=True, slots=True)
class BundleEntry:
    """One shared template: a current revision, and what it needs to print."""

    id: str
    name: str
    label_size_id: str
    revision: int
    document: Mapping[str, Any]
    digest: str
    provenance: Provenance
    dependencies: Mapping[str, tuple[str, ...]]

    def as_dict(self) -> dict[str, Any]:
        """Return the entry's bundle form."""
        return {
            "id": self.id,
            "name": self.name,
            "label_size_id": self.label_size_id,
            "revision": self.revision,
            "document": dict(self.document),
            "digest": self.digest,
            "provenance": self.provenance.as_dict(),
            "dependencies": {
                kind: list(self.dependencies.get(kind, ())) for kind in DEPENDENCY_KINDS
            },
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> BundleEntry:
        """Read one entry, refusing anything that is not one."""
        if not isinstance(value, Mapping):
            raise BundleNotReadable("a template entry is not an object.")
        try:
            return cls(
                id=_text(value, "id"),
                name=_text(value, "name"),
                label_size_id=_text(value, "label_size_id"),
                revision=int(value["revision"]),
                document=_mapping(value, "document"),
                digest=_text(value, "digest"),
                provenance=Provenance.from_dict(_mapping(value, "provenance")),
                dependencies={
                    kind: tuple(
                        str(item)
                        for item in (value.get("dependencies") or {}).get(kind, ())
                    )
                    for kind in DEPENDENCY_KINDS
                },
            )
        except (KeyError, TypeError, ValueError) as err:
            raise BundleNotReadable(f"a template entry is malformed ({err}).") from err


@dataclass(frozen=True, slots=True)
class TemplateBundle:
    """One portable bundle, verified as far as its own bytes can verify it."""

    entries: tuple[BundleEntry, ...]
    exported_at: str
    version: int = BUNDLE_VERSION

    def as_dict(self) -> dict[str, Any]:
        """Return the bundle document, checksum and all."""
        payload = self._payload()
        return {**payload, "checksum": digest(payload)}

    def _payload(self) -> dict[str, Any]:
        """Return everything the checksum is taken over."""
        return {
            "schema": BUNDLE_SCHEMA,
            "version": self.version,
            "layout_schema": SCHEMA,
            "layout_schema_version": VERSION,
            "catalogues": {
                "label_sizes": LABEL_SIZE_CATALOGUE_VERSION,
                "bindings": BINDING_CATALOGUE_VERSION,
                "style_tokens": STYLE_TOKEN_CATALOGUE_VERSION,
            },
            "exported_at": self.exported_at,
            "templates": [entry.as_dict() for entry in self.entries],
        }


def build_bundle(
    templates: Iterable[NamedTemplate], *, exported_at: str
) -> TemplateBundle:
    """Bundle each template's current head, as saved.

    Unvalidated on purpose. A Quarantined Template is one of the things an
    administrator most needs to be able to hand to somebody -- to a colleague
    with a newer integration, or back to themselves after an upgrade -- and
    refusing to export what cannot be printed today would make the export
    useless exactly when it matters. The import is where a document has to be
    something this installation can compile.
    """
    return TemplateBundle(
        entries=tuple(_entry_of(template) for template in templates),
        exported_at=exported_at,
    )


def read_bundle(value: object) -> TemplateBundle:
    """Read one bundle, verifying it before anything in it is interpreted."""
    if not isinstance(value, Mapping):
        raise BundleNotReadable("a bundle is a JSON object.")
    if value.get("schema") != BUNDLE_SCHEMA:
        raise BundleNotReadable(
            f"its schema is {value.get('schema')!r}, not {BUNDLE_SCHEMA!r}."
        )
    found = value.get("version")
    if not isinstance(found, int) or isinstance(found, bool) or found < 1:
        raise BundleNotReadable(f"{found!r} is not a bundle format version.")
    if found > BUNDLE_VERSION:
        raise IncompatibleBundle(found=found, supported=BUNDLE_VERSION)

    templates = value.get("templates")
    if not isinstance(templates, Sequence) or isinstance(templates, (str, bytes)):
        raise BundleNotReadable("its `templates` is not a list.")
    bundle = migrate(
        TemplateBundle(
            entries=tuple(BundleEntry.from_dict(item) for item in templates),
            exported_at=str(value.get("exported_at", "")),
            version=found,
        )
    )
    _verify_checksum(value, bundle)
    return bundle


def migrate(bundle: TemplateBundle) -> TemplateBundle:
    """Lift one bundle to the current format, in memory.

    There is one format, so this is the identity today. It exists as a named
    seam anyway: the alternative to one function that every older version is
    lifted through is a version check at each field, which is how a format
    ends up migrated in six places and not at all in a seventh.
    """
    return bundle


def dependencies_of(document: object) -> dict[str, tuple[str, ...]]:
    """Return everything one stored document refers to, by kind.

    Read off the raw document rather than a parsed layout, because the
    documents that most need their dependencies named are exactly the ones
    that no longer parse.
    """
    found: dict[str, set[str]] = {kind: set() for kind in DEPENDENCY_KINDS}
    if not isinstance(document, Mapping):
        return dict.fromkeys(DEPENDENCY_KINDS, ())
    if isinstance(size := document.get("label_size_id"), str):
        found["label_sizes"].add(size)
    elements = document.get("elements")
    if isinstance(elements, Sequence) and not isinstance(elements, (str, bytes)):
        for element in elements:
            if isinstance(element, Mapping):
                _element_dependencies(element, found)
    return {kind: tuple(sorted(values)) for kind, values in found.items()}


def unknown_dependencies(
    dependencies: Mapping[str, Sequence[str]],
) -> tuple[str, ...]:
    """Return every dependency this installation does not have, spelled out.

    Spelled `kind:id` because the pair is the whole message: an administrator
    told that `growspace.stock.60x40.v1` is missing knows to look for the
    integration that ships it, where "one unknown dependency" sends them
    nowhere.
    """
    missing: list[str] = []
    for kind, catalogue in _CATALOGUES.items():
        missing.extend(
            f"{kind}:{item}"
            for item in dependencies.get(kind, ())
            if item not in catalogue
        )
    return tuple(missing)


def _entry_of(template: NamedTemplate) -> BundleEntry:
    """Turn one template's head into a shareable entry."""
    head = template.head
    return BundleEntry(
        id=template.id,
        name=head.name,
        label_size_id=template.label_size_id,
        revision=head.revision,
        document=dict(head.document),
        digest=head.digest,
        provenance=_shareable(head.provenance),
        dependencies=dependencies_of(head.document),
    )


def _shareable(provenance: Provenance) -> Provenance:
    """Return provenance with the parts that mean nothing elsewhere removed.

    The draft a revision was published from is one installation's private
    editing state: its ID is meaningless on another, and carrying it would
    invite a replayed publication over there to match a draft that never
    existed. What travels is structural -- which factory design, which
    template, which revision.
    """
    return Provenance(
        source=provenance.source,
        factory_id=provenance.factory_id,
        factory_revision=provenance.factory_revision,
        source_template_id=provenance.source_template_id,
        source_revision=provenance.source_revision,
    )


def _verify_checksum(value: Mapping[str, Any], bundle: TemplateBundle) -> None:
    """Refuse a bundle whose checksum does not describe what it carries."""
    claimed = value.get("checksum")
    if not isinstance(claimed, str) or not claimed:
        raise BundleNotReadable("it carries no checksum.")
    if claimed != bundle.as_dict()["checksum"]:
        raise BundleNotReadable(
            "its checksum does not match its contents, so it was damaged or "
            "edited after it was written."
        )


def _element_dependencies(
    element: Mapping[str, Any], found: dict[str, set[str]]
) -> None:
    """Collect one element's catalogue references into `found`."""
    content = element.get("content")
    if isinstance(content, Mapping):
        if isinstance(binding := content.get("binding"), str):
            found["bindings"].add(binding)
        if isinstance(asset := content.get("asset_id"), str):
            found["assets"].add(asset)
    style = element.get("style")
    if isinstance(style, Mapping):
        for key, kind in (
            ("font", "fonts"),
            ("line_spacing", "line_spacings"),
            ("monochrome", "monochromes"),
        ):
            if isinstance(value := style.get(key), str):
                found[kind].add(value)


def _text(value: Mapping[str, Any], key: str) -> str:
    """Read one required string field of a bundle entry."""
    found = value[key]
    if not isinstance(found, str) or not found:
        raise TypeError(f"{key} is not a non-empty string")
    return found


def _mapping(value: Mapping[str, Any], key: str) -> dict[str, Any]:
    """Read one required object field of a bundle entry."""
    found = value[key]
    if not isinstance(found, Mapping):
        raise TypeError(f"{key} is not an object")
    return dict(found)
