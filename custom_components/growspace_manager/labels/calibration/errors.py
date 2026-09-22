"""What the calibration route refuses, and why -- one type per reason.

Each of these is a state a correct client can reach, so each says what
happened rather than that something went wrong. They subclass the
integration's own error base, the way the template library's refusals do.

Authorization is deliberately not here. A non-administrator asking to record a
calibration raises Home Assistant's own `Unauthorized`, because that is the
same refusal every privileged command in Home Assistant makes.
"""

from __future__ import annotations

from ...exceptions import GrowspaceError


class CalibrationError(GrowspaceError):
    """Base error for every local-calibration refusal."""


class IncompatibleCalibrationStore(CalibrationError):
    """The stored calibration history was written by a newer version.

    Left untouched rather than read loosely: a best-effort read of a newer
    document is how it quietly becomes a lossy older one, and this one is an
    audit record.
    """

    def __init__(self, found: int, supported: int) -> None:
        """Name both versions, so a repair issue can say which is which."""
        self.found = found
        self.supported = supported
        super().__init__(
            f"The label calibration store is at version {found}; this "
            f"Growspace Manager reads version {supported}."
        )


class CalibrationSheetNotPrinted(CalibrationError):
    """The calibration label could not be put on paper, so nothing was measured.

    Recording a measurement read off a sheet that never printed would attach
    four numbers to a render that did not happen.
    """

    def __init__(self, detail: str) -> None:
        """Say what the renderer or the printer reported."""
        super().__init__(f"The calibration label was not printed: {detail}")
