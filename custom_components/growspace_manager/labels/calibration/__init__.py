"""[[Local Calibration]]: where one installed printer really puts ink.

Two independent proofs stand between a layout and a production print, and
this package is one of them. **Product verification** says a printer class,
stock, orientation, toolchain and density mapping have passed a physical
evidence matrix; it lives in the Capability Profile. **Local calibration**
says where *this* printer, with *this* roll on it, lands the marks. Neither
substitutes for the other: one alignment label cannot establish that a font is
readable or a QR scans, and no amount of product evidence can know that the
roll in the machine is loaded 0.8 mm off.

The route is four steps, and the seams between them are the point:

    profile          ->  sheet.calibration_layout    ->  the standardized label
    the label        ->  printing.async_print_calibration_label  ->  paper
    what was printed ->  records.CalibrationDependencies.from_render
    read off paper   ->  ledger.async_record         ->  an immutable record

The measurement is recorded against the identities of the sheet that was
actually printed rather than against current state, so four numbers can never
be attached to a render that did not happen. Afterwards a print asks the
ledger one question -- is this printer's newest measurement still true of what
I am about to do? -- and gets one of three answers: it was never measured,
something it depended on moved and here is the field, or it is current and
here is the identity to carry in the Render Context.

Nothing here is ever rewritten. Re-calibrating appends; a superseded record
stays, because "what was this printer measured at when that label printed?"
has to keep having an answer.

Nothing here is registered as a service or a websocket command yet. The
Template Capability is advertised as one complete envelope once every required
v1 operation exists.
"""

from __future__ import annotations

from .errors import (
    CalibrationError,
    CalibrationSheetNotPrinted,
    IncompatibleCalibrationStore,
)
from .ledger import (
    LocalCalibrationLedger,
    async_get_calibration_ledger,
    async_release_calibration_ledger,
    required_dependencies,
)
from .records import (
    EDGES,
    STORE_SCHEMA,
    STORE_VERSION,
    CalibrationDependencies,
    CalibrationLedgerState,
    CalibrationScope,
    LocalCalibration,
    MeasurementBounds,
    MeasurementInvalid,
    PlacementMeasurement,
    validate_measurement,
)
from .sheet import (
    CALIBRATION_SOURCE,
    ELEMENT_PREFIX,
    MINIMUM_PRINTABLE_HEIGHT_MM,
    MINIMUM_PRINTABLE_WIDTH_MM,
    SHEET_VERSION,
    TICK_COUNT,
    TICK_PITCH_MM,
    CalibrationSheetUnavailable,
    calibration_content,
    calibration_layout,
)
from .staleness import (
    ABSENT,
    AGE_WARNING,
    CURRENT,
    RECHECK_AFTER,
    STALE,
    CalibrationStatus,
    evaluate,
)
from .store import STORAGE_KEY_PREFIX, CalibrationStore, storage_key

__all__ = [
    "ABSENT",
    "AGE_WARNING",
    "CALIBRATION_SOURCE",
    "CURRENT",
    "EDGES",
    "ELEMENT_PREFIX",
    "MINIMUM_PRINTABLE_HEIGHT_MM",
    "MINIMUM_PRINTABLE_WIDTH_MM",
    "RECHECK_AFTER",
    "SHEET_VERSION",
    "STALE",
    "STORAGE_KEY_PREFIX",
    "STORE_SCHEMA",
    "STORE_VERSION",
    "TICK_COUNT",
    "TICK_PITCH_MM",
    "CalibrationDependencies",
    "CalibrationError",
    "CalibrationLedgerState",
    "CalibrationScope",
    "CalibrationSheetNotPrinted",
    "CalibrationSheetUnavailable",
    "CalibrationStatus",
    "CalibrationStore",
    "IncompatibleCalibrationStore",
    "LocalCalibration",
    "LocalCalibrationLedger",
    "MeasurementBounds",
    "MeasurementInvalid",
    "PlacementMeasurement",
    "async_get_calibration_ledger",
    "async_release_calibration_ledger",
    "calibration_content",
    "calibration_layout",
    "evaluate",
    "required_dependencies",
    "storage_key",
    "validate_measurement",
]
