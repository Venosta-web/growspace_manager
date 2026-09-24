# Growspace reliability evidence

Call `growspace_manager.export_reliability_evidence` with `growspace_id` and
`return_response: true` to retrieve a JSON summary. The service returns the
document to the requesting Home Assistant client. It does not upload or send
anything to Growspace Manager or another service.

The response has `schema_version: 1`, `unreadable`, `growspace_id`, UTC `as_of`,
`days_since_last_fault` (null until a fault is observed), and three counter maps:
`lifetime`, `last_24h`, and `last_30d`. Counter names are stable dotted keys;
absent counters mean zero. `runtime.automation_uptime_percent` is null
when no runtime minute has been sampled. The diagnostic sensor's state is the
lifetime count of `irrigation.completed_verified`; its attributes contain the
same document. Config entry diagnostics include one such document per growspace.
If the evidence store cannot be decoded, `unreadable` is true, the diagnostic
sensor is unavailable, and the integration leaves the stored file untouched.

The lifetime map survives restarts. The 24-hour map stores minute buckets and
the 30-day map stores UTC calendar-day buckets. At a boundary, the former has
minute resolution and the latter has day resolution. Old buckets are pruned on
the next write, so persisted storage stays bounded by 1,441 minute buckets and
31 day buckets per growspace plus the lifetime map. A growspace with no recent
events has empty recent maps apart from the derived uptime value.

`irrigation.completed_verified` means the pump read ON and subsequently read
OFF after the planned cycle. `irrigation.completed_unverified` means it read ON
but did not confirm OFF. `runtime.estimated_water_l` uses the configured pump
rate and observed runtime; it is an estimate, not metered water. Automated
runtime is keyed by actuator entity ID. Sensor unavailable minutes are sampled
once a minute while the integration is running. Stale events use a five-minute
last-reported threshold; implausible readings cover soil moisture outside
0–100% or non-finite values. Automation uptime is the percentage of observed
minutes when automatic irrigation is armed and no fault is latched.
