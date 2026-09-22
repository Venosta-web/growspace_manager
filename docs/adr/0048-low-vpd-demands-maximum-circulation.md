# Low VPD Demands Maximum Circulation

**Status:** Accepted

Circulation VPD mode uses an inverted linear response: a reading at or below `target − tolerance` demands the grower-configured `max_speed`, a reading at or above `target + tolerance` demands `min_speed`, and readings inside the band interpolate downward through the configured range. Low VPD is a demand signal for protective canopy airflow and mold-risk mitigation, not a promise that an internal fan will regulate ambient VPD; exhaust and dehumidification remain responsible for removing moisture. At maximum low-VPD demand, negative dynamic-wind modulation is suppressed so the fan actually remains at its configured ceiling. Existing VPD-mode installations adopt this corrected direction directly because retaining the opposite behavior would preserve a hazardous controller trap.

The controller uses the lowest valid configured VPD reading so the most humid measured canopy zone drives demand. Invalid and unavailable readings are ignored, and if none remain the controller retains its last command rather than inferring low VPD from missing data. Bayesian mold-risk output is not fed back into fan demand, avoiding a loop in which fan state contributes to the signal that controls the fan. A configured zero minimum remains valid, and binary actuators interpret demand above the minimum as on.
