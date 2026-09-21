"""What one [[Local Calibration]] is, and what it is only true of.

A calibration is a measurement of one installed printer: where it really puts
ink on one stock, mounted one way round, driven by one toolchain. It is not a
property of the printer model, and it is not evidence that the model works --
[[Capability Profile]] evidence is the other proof, and neither stands in for
the other.

Three values hold the whole of it apart:

    scope         which records are candidates for one print at all
    fingerprint   whether the newest candidate is still true
    measurement   what the operator read off the calibration label

The **scope** is the installed device, its printer class, the stock and the
orientation. Change any of those and you are not looking at a different
version of the same measurement, you are looking at a different printer or a
different roll, and the old record is simply not a candidate.

The **fingerprint** is everything a measurement silently depended on: the
resolution, the printhead, the declared Printable Area, the density mapping,
the calibrated limits, the compiler, renderer and adapter, the fonts, the
catalogues, the calibration sheet itself and -- where an installation can read
it -- the firmware. A candidate whose fingerprint has moved is **stale**, and
staleness names the field that moved rather than reporting that something did.

The **measurement** is four edge offsets and one signed feed displacement.
What each number means is in `PlacementMeasurement`, because a calibration
nobody can re-enter the same way is not a record, it is a number.

Nothing here is ever rewritten. A second calibration of the same scope is a
second record appended beside the first: the audit question "what was this
printer measured at when that label was printed?" has to keep having an
answer.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from ..canonical.canonicalization import digest
from ..canonical.catalogue import (
    BINDING_CATALOGUE_VERSION,
    CAPABILITY_GENERATION,
    LABEL_SIZE_CATALOGUE_VERSION,
    STYLE_TOKEN_CATALOGUE_VERSION,
)
from ..canonical.compiler import COMPILER_VERSION
from ..canonical.document import QUANTUM_MM
from ..canonical.fonts import TEXT_TOOLCHAIN_VERSION
from ..canonical.profiles import CapabilityProfile
from ..canonical.qr import QR_MODEL_VERSION
from ..canonical.result import ADAPTER_VERSION, RENDERER_VERSION, RenderContext
from ..canonical.safety import SAFETY_POLICY_VERSION

#: Bumped when the persisted shape below changes. A store written at a newer
#: version is refused rather than read loosely.
STORE_VERSION = 1

#: The document `schema` field, so a backup carried between installations says
#: what it is without being guessed at.
STORE_SCHEMA = "growspace.label-calibration"

#: The four edges a calibration measures, in the stock's own unrotated
#: coordinate system -- which is the only system the Printable Area is ever
#: expressed in.
EDGES = ("top", "right", "bottom", "left")


class MeasurementInvalid(ValueError):
    """One entered measurement is not a number this label could have shown."""

    def __init__(self, message: str, *, field: str | None = None) -> None:
        """Say what is wrong, and which entered value it is wrong about.

        `field` is what lets a form put the refusal beside the box it came
        from rather than above all five of them.
        """
        super().__init__(message)
        self.field = field


@dataclass(frozen=True, slots=True)
class PlacementMeasurement:
    """What the operator read off one calibration label.

    The four edge values are each **how much of the declared Printable Area
    this printer does not reach on that edge**, in millimetres, read from that
    edge's scale on the sheet: the first tick that printed is the first
    millimetre position the printer can reach, and the distance back to the
    declared edge is the offset. Zero means the printer reached the declared
    edge; there is no negative value, because a printer that reaches *further*
    than the declared area is a profile that understates itself and is a
    profile correction rather than a local measurement.

    `feed_mm` is signed, and it is the one that has to be. It is the
    displacement of the feed ruler's centre tick from the printable area's
    midpoint along the profile's feed axis: positive where the sheet printed
    later than it should have -- the media running long -- and negative where
    it printed early. Both happen, and a measurement that could only say
    "wrong by 0.8 mm" would not be one anybody could correct from.
    """

    top_mm: float
    right_mm: float
    bottom_mm: float
    left_mm: float
    feed_mm: float

    def as_dict(self) -> dict[str, float]:
        """Return the measurement's persisted form."""
        return {
            "top_mm": self.top_mm,
            "right_mm": self.right_mm,
            "bottom_mm": self.bottom_mm,
            "left_mm": self.left_mm,
            "feed_mm": self.feed_mm,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> PlacementMeasurement:
        """Read one persisted measurement."""
        return cls(
            top_mm=float(value["top_mm"]),
            right_mm=float(value["right_mm"]),
            bottom_mm=float(value["bottom_mm"]),
            left_mm=float(value["left_mm"]),
            feed_mm=float(value["feed_mm"]),
        )


@dataclass(frozen=True, slots=True)
class MeasurementBounds:
    """The geometry a measurement has to be possible on.

    Taken from a profile when a sheet is about to be printed and from a
    record's own dependencies when its numbers are entered, which is the
    whole point of it being a value rather than a profile: a measurement must
    be admitted against the geometry it was taken on, not against whichever
    profile happens to be selected when the form is submitted.
    """

    printable_width_mm: float
    printable_height_mm: float
    feed_axis: str

    @classmethod
    def of_profile(cls, profile: CapabilityProfile) -> MeasurementBounds:
        """The bounds one Capability Profile declares."""
        return cls(
            printable_width_mm=profile.printable_width_mm,
            printable_height_mm=profile.printable_height_mm,
            feed_axis=str(profile.feed_axis),
        )

    @classmethod
    def of_dependencies(
        cls, dependencies: CalibrationDependencies
    ) -> MeasurementBounds:
        """The bounds the printed sheet's own dependencies recorded."""
        return cls(
            printable_width_mm=dependencies.printable_width_mm,
            printable_height_mm=dependencies.printable_height_mm,
            feed_axis=dependencies.feed_axis,
        )


def validate_measurement(
    measurement: PlacementMeasurement, bounds: MeasurementBounds
) -> PlacementMeasurement:
    """Return the measurement, or say which entered value cannot be one.

    Three things are checked, and none of them is a plausibility opinion.
    Every value is quantized to the product's own millimetre quantum, so a
    calibration cannot carry a precision the document model does not have. An
    edge offset is non-negative, for the reason `PlacementMeasurement` gives.
    And no value may exceed the printable extent of the axis it is on: an
    offset larger than the Printable Area is not a printer that clips, it is a
    digit entered in the wrong box, and storing it would silently make every
    later print ineligible for a reason nobody could find.

    What is deliberately *not* checked is whether the number is small. A badly
    loaded roll really does lose four millimetres, and a validator that called
    that implausible would be refusing the measurement most worth having.
    """
    extents = {
        "top_mm": bounds.printable_height_mm,
        "bottom_mm": bounds.printable_height_mm,
        "left_mm": bounds.printable_width_mm,
        "right_mm": bounds.printable_width_mm,
        "feed_mm": (
            bounds.printable_height_mm
            if bounds.feed_axis == "y"
            else bounds.printable_width_mm
        ),
    }
    for name, value in measurement.as_dict().items():
        _quantized(name, value)
        if name != "feed_mm" and value < 0:
            raise MeasurementInvalid(
                f"{name} is {value} mm; an edge offset is how much of the "
                "Printable Area is lost, which cannot be negative.",
                field=name,
            )
        if abs(value) > extents[name]:
            raise MeasurementInvalid(
                f"{name} is {value} mm, which is outside the "
                f"{extents[name]} mm the Printable Area has on that axis.",
                field=name,
            )
    return measurement


def _quantized(name: str, value: float) -> None:
    """Refuse a measurement finer than the millimetre quantum, never round it."""
    try:
        remainder = Decimal(str(value)).remainder_near(QUANTUM_MM)
    except InvalidOperation as err:  # pragma: no cover - non-finite input
        raise MeasurementInvalid(
            f"{name} is not a millimetre value.", field=name
        ) from err
    if remainder != 0:
        raise MeasurementInvalid(
            f"{name} is {value} mm, which is not a multiple of {QUANTUM_MM} mm.",
            field=name,
        )


@dataclass(frozen=True, slots=True)
class CalibrationScope:
    """Which printer, stock and mounting one measurement is of.

    Four values, and they select rather than validate: a record outside this
    scope is not a stale calibration of this print, it is a calibration of
    something else.
    """

    device_id: str
    printer_class: str
    label_size_id: str
    orientation: str

    def as_dict(self) -> dict[str, str]:
        """Return the scope's persisted form."""
        return {
            "device_id": self.device_id,
            "printer_class": self.printer_class,
            "label_size_id": self.label_size_id,
            "orientation": self.orientation,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> CalibrationScope:
        """Read one persisted scope."""
        return cls(
            device_id=str(value["device_id"]),
            printer_class=str(value["printer_class"]),
            label_size_id=str(value["label_size_id"]),
            orientation=str(value["orientation"]),
        )


@dataclass(frozen=True, slots=True)
class CalibrationDependencies:
    """Everything one measurement was only true of, named field by field.

    Built from the Render Context of the calibration label that was actually
    printed rather than assembled beside it, so the identities recorded are
    the ones the sheet in the operator's hand came out of. That is the whole
    reason `from_render` takes a context: a dependency list composed from
    current state would be a description of the moment the form was submitted,
    not of the print it describes.

    Two absences are deliberate.

    **The selected density is not here.** Density is heat, not placement, and
    a record that went stale every time somebody printed darker would be
    asking for a re-measurement of something that did not move. The density
    *mapping* is here, because a profile that redefines what `normal` means on
    this hardware has changed what the calibration sheet was printed with.

    **The profile's evidence state is not here either.** Promotion from
    provisional to product-verified is exactly the transition a calibration is
    taken in anticipation of; staling every installation's measurement at the
    moment the product learns its printer works would mean nobody could ever
    be ready. What promotion may also change -- the calibrated limits, the
    declared geometry -- is covered by the fields that describe those.
    """

    scope: CalibrationScope
    feed_axis: str
    dpi: int
    printhead_pixels: int
    printable_origin_x_mm: float
    printable_origin_y_mm: float
    printable_width_mm: float
    printable_height_mm: float
    safe_area_inset_mm: float
    density_levels: Mapping[str, int]
    limits_digest: str
    sheet_version: str
    compiler_version: str
    renderer_version: str
    adapter_version: str
    text_toolchain_version: str
    qr_model_version: str
    safety_policy_version: str
    binding_catalogue_version: str
    style_token_catalogue_version: str
    label_size_catalogue_version: str
    capability_generation: int
    #: Every shipped face's digest, as this installation resolves them. The
    #: installation's font identity rather than one render's: a calibration
    #: sheet and a strain label use different faces, so a per-render identity
    #: would differ on every print and stale every measurement at once.
    font_identity: Mapping[str, str] = field(default_factory=dict)
    #: What the installation could read of the printer's firmware. `None` is
    #: an honest answer, and a consistent one: an installation that cannot
    #: read firmware records the same absence every time rather than
    #: alternating between a version and a gap.
    firmware: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return the dependencies' persisted form, which is also what hashes."""
        return {
            "scope": self.scope.as_dict(),
            "feed_axis": self.feed_axis,
            "dpi": self.dpi,
            "printhead_pixels": self.printhead_pixels,
            "printable_origin_x_mm": self.printable_origin_x_mm,
            "printable_origin_y_mm": self.printable_origin_y_mm,
            "printable_width_mm": self.printable_width_mm,
            "printable_height_mm": self.printable_height_mm,
            "safe_area_inset_mm": self.safe_area_inset_mm,
            "density_levels": dict(self.density_levels),
            "limits_digest": self.limits_digest,
            "sheet_version": self.sheet_version,
            "compiler_version": self.compiler_version,
            "renderer_version": self.renderer_version,
            "adapter_version": self.adapter_version,
            "text_toolchain_version": self.text_toolchain_version,
            "qr_model_version": self.qr_model_version,
            "safety_policy_version": self.safety_policy_version,
            "binding_catalogue_version": self.binding_catalogue_version,
            "style_token_catalogue_version": self.style_token_catalogue_version,
            "label_size_catalogue_version": self.label_size_catalogue_version,
            "capability_generation": self.capability_generation,
            "font_identity": dict(self.font_identity),
            "firmware": self.firmware,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> CalibrationDependencies:
        """Read one persisted dependency set."""
        return cls(
            scope=CalibrationScope.from_dict(value["scope"]),
            feed_axis=str(value["feed_axis"]),
            dpi=int(value["dpi"]),
            printhead_pixels=int(value["printhead_pixels"]),
            printable_origin_x_mm=float(value["printable_origin_x_mm"]),
            printable_origin_y_mm=float(value["printable_origin_y_mm"]),
            printable_width_mm=float(value["printable_width_mm"]),
            printable_height_mm=float(value["printable_height_mm"]),
            safe_area_inset_mm=float(value["safe_area_inset_mm"]),
            density_levels={
                str(name): int(level)
                for name, level in dict(value["density_levels"]).items()
            },
            limits_digest=str(value["limits_digest"]),
            sheet_version=str(value["sheet_version"]),
            compiler_version=str(value["compiler_version"]),
            renderer_version=str(value["renderer_version"]),
            adapter_version=str(value["adapter_version"]),
            text_toolchain_version=str(value["text_toolchain_version"]),
            qr_model_version=str(value["qr_model_version"]),
            safety_policy_version=str(value["safety_policy_version"]),
            binding_catalogue_version=str(value["binding_catalogue_version"]),
            style_token_catalogue_version=str(value["style_token_catalogue_version"]),
            label_size_catalogue_version=str(value["label_size_catalogue_version"]),
            capability_generation=int(value["capability_generation"]),
            font_identity={
                str(name): str(item)
                for name, item in dict(value.get("font_identity", {})).items()
            },
            firmware=(
                None if value.get("firmware") is None else str(value["firmware"])
            ),
        )

    @property
    def identity(self) -> str:
        """The digest two dependency sets must share to be the same one."""
        return digest(self.as_dict())

    def differences(self, other: CalibrationDependencies) -> tuple[str, ...]:
        """Name every field in which `other` differs from this one.

        Names, in declared order, rather than a boolean -- because "your
        printer needs re-measuring" is not an instruction anybody can act on
        and "the renderer version changed" is.
        """
        mine = self.as_dict()
        theirs = other.as_dict()
        return tuple(name for name in mine if mine[name] != theirs.get(name))

    @classmethod
    def from_render(
        cls,
        context: RenderContext,
        profile: CapabilityProfile,
        *,
        device_id: str,
        sheet_version: str,
        font_identity: Mapping[str, str],
        firmware: str | None = None,
    ) -> CalibrationDependencies:
        """Capture what the calibration label that was just printed depended on.

        The toolchain versions are read off the Render Context of that print
        rather than from this module's imports, so what is recorded is what
        the sheet in the operator's hand came out of. The font identity is not
        the context's, for the reason the field says.
        """
        return cls(
            **_geometry_of(profile, device_id=device_id),
            sheet_version=sheet_version,
            compiler_version=context.compiler_version,
            renderer_version=context.renderer_version,
            adapter_version=context.adapter_version,
            text_toolchain_version=context.text_toolchain_version,
            qr_model_version=context.qr_model_version,
            safety_policy_version=context.safety_policy_version,
            binding_catalogue_version=context.binding_catalogue_version,
            style_token_catalogue_version=context.style_token_catalogue_version,
            label_size_catalogue_version=context.label_size_catalogue_version,
            capability_generation=context.capability_generation,
            font_identity=dict(font_identity),
            firmware=firmware,
        )

    @classmethod
    def for_profile(
        cls,
        profile: CapabilityProfile,
        *,
        device_id: str,
        sheet_version: str,
        font_identity: Mapping[str, str],
        firmware: str | None = None,
    ) -> CalibrationDependencies:
        """What a print about to happen needs a calibration to have been of.

        The same values `from_render` records, taken from the running code
        instead of from a context -- because a print has to know what it
        requires before it has rendered anything, and a two-render dance to
        find out would make the second render the authority on its own
        eligibility.

        The two builders must agree for the same profile and installation, and
        the suite asserts exactly that. Where they ever do not, the difference
        names the toolchain version that moved, which is the answer anyway.
        """
        return cls(
            **_geometry_of(profile, device_id=device_id),
            sheet_version=sheet_version,
            compiler_version=COMPILER_VERSION,
            renderer_version=RENDERER_VERSION,
            adapter_version=ADAPTER_VERSION,
            text_toolchain_version=TEXT_TOOLCHAIN_VERSION,
            qr_model_version=QR_MODEL_VERSION,
            safety_policy_version=SAFETY_POLICY_VERSION,
            binding_catalogue_version=BINDING_CATALOGUE_VERSION,
            style_token_catalogue_version=STYLE_TOKEN_CATALOGUE_VERSION,
            label_size_catalogue_version=LABEL_SIZE_CATALOGUE_VERSION,
            capability_generation=CAPABILITY_GENERATION,
            font_identity=dict(font_identity),
            firmware=firmware,
        )


def _geometry_of(profile: CapabilityProfile, *, device_id: str) -> dict[str, Any]:
    """The scope and declared geometry both dependency builders share."""
    return {
        "scope": CalibrationScope(
            device_id=device_id,
            printer_class=profile.printer_class,
            label_size_id=profile.label_size_id,
            orientation=str(profile.orientation),
        ),
        "feed_axis": str(profile.feed_axis),
        "dpi": profile.dpi,
        "printhead_pixels": profile.printhead_pixels,
        "printable_origin_x_mm": profile.printable_origin_x_mm,
        "printable_origin_y_mm": profile.printable_origin_y_mm,
        "printable_width_mm": profile.printable_width_mm,
        "printable_height_mm": profile.printable_height_mm,
        "safe_area_inset_mm": profile.safe_area_inset_mm,
        "density_levels": dict(profile.density_levels),
        "limits_digest": digest(profile.limits.as_dict()),
    }


@dataclass(frozen=True, slots=True)
class LocalCalibration:
    """One immutable record of one printer measured once.

    `identity` is what a Render Context carries as its `local_calibration`, so
    a raster rendered against this measurement cannot be confused with one
    rendered against the next. It covers the measurement and the dependencies
    but not the record's own ID or the actor: two administrators entering the
    same numbers for the same printer have measured the same thing, and a
    cached raster should not be invalidated because a different person held
    the ruler.
    """

    id: str
    recorded_at: str
    recorded_by: str
    measurement: PlacementMeasurement
    dependencies: CalibrationDependencies
    #: The raster identity of the calibration label this measures. It is the
    #: audit trail's other half: the numbers are only meaningful next to the
    #: exact sheet they were read off.
    sheet_raster_identity: str
    #: The density the sheet was printed at. Recorded, and deliberately not a
    #: dependency -- see `CalibrationDependencies`.
    printed_density: str
    notes: str | None = None

    @property
    def scope(self) -> CalibrationScope:
        """Which printer, stock and mounting this record is of."""
        return self.dependencies.scope

    @property
    def identity(self) -> str:
        """The identity a Render Context records for this measurement."""
        return digest(
            {
                "measurement": self.measurement.as_dict(),
                "dependencies": self.dependencies.as_dict(),
            }
        )

    def as_dict(self) -> dict[str, Any]:
        """Return the record's persisted form."""
        return {
            "id": self.id,
            "recorded_at": self.recorded_at,
            "recorded_by": self.recorded_by,
            "measurement": self.measurement.as_dict(),
            "dependencies": self.dependencies.as_dict(),
            "sheet_raster_identity": self.sheet_raster_identity,
            "printed_density": self.printed_density,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> LocalCalibration:
        """Read one persisted record."""
        return cls(
            id=str(value["id"]),
            recorded_at=str(value["recorded_at"]),
            recorded_by=str(value["recorded_by"]),
            measurement=PlacementMeasurement.from_dict(value["measurement"]),
            dependencies=CalibrationDependencies.from_dict(value["dependencies"]),
            sheet_raster_identity=str(value["sheet_raster_identity"]),
            printed_density=str(value["printed_density"]),
            notes=None if value.get("notes") is None else str(value["notes"]),
        )

    def summary(self) -> dict[str, Any]:
        """Return the record with its identity beside it, for a listing."""
        return {**self.as_dict(), "identity": self.identity}


@dataclass(frozen=True, slots=True)
class CalibrationLedgerState:
    """One config entry's complete calibration history.

    A flat append-only list rather than a mapping keyed by scope, because the
    thing being kept is a history and a mapping would make replacing the
    newest record the natural operation. Ordering is chronological by
    insertion, so "the newest record for this scope" is a scan backwards and
    an older record is never in the way of finding it.
    """

    records: tuple[LocalCalibration, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        """Return the complete persisted document."""
        return {
            "schema": STORE_SCHEMA,
            "version": STORE_VERSION,
            "records": [record.as_dict() for record in self.records],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | None) -> CalibrationLedgerState:
        """Read one persisted document, or start an empty one."""
        if not value:
            return cls()
        raw = value.get("records")
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            return cls()
        return cls(records=tuple(LocalCalibration.from_dict(item) for item in raw))

    def appended(self, record: LocalCalibration) -> CalibrationLedgerState:
        """Return this ledger with one more record at the end."""
        return CalibrationLedgerState(records=(*self.records, record))

    def within(self, scope: CalibrationScope) -> tuple[LocalCalibration, ...]:
        """Every record of one printer, stock and mounting, oldest first."""
        return tuple(record for record in self.records if record.scope == scope)

    def newest(self, scope: CalibrationScope) -> LocalCalibration | None:
        """The most recently recorded measurement of one scope, if there is one."""
        within = self.within(scope)
        return within[-1] if within else None
