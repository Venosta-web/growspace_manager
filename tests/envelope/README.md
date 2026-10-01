# Irrigation scale envelope

ADR-0060's executable bound is ten growspaces, six zones apiece, and four
moisture plus four pore-EC probes per zone. `test_load.py` drives 10,080 minute
ticks on Home Assistant with fake time, instant confirming actuator drivers,
and the production zone runtimes, steering machines, substrate trackers and
Supply Queue. Each zone delivers forty steering shots per day for seven days.
Control and witness probes report every minute; the moisture response rises
after each shot so the response guard is exercised without intentionally
turning this performance test into a degraded-control test.

Each sensor callback shares its control sample across alerting, reference-day
tracking and witness notices; steering uses its own fresh sample. Unchanged
immutable attempt histories also reuse their daily-cap aggregate.

The p99 budget is 100 ms for the sensor/control and steering callbacks across
the entire instance. The supply effects run in their background tasks after
the callbacks, as in production. Device waits and disk latency are excluded;
the real store's encoding and retention execute, and **every** synchronous and
delayed write is serialized using Home Assistant's JSON encoder. Each payload,
including the storage wrapper, must be at most 150,000 bytes. Every write also
checks the 2,000-row ceiling and retention of all rows charged that local day.
The final stores are decoded and compared against their in-memory attempts.

CI runs this benchmark separately from coverage and includes its measurements
in `envelope.xml` and the workflow job summary. `no_cover` also keeps the measurement meaningful when the
full local suite runs with coverage. The ordinary unit-test CI step excludes
`test_load.py` to avoid running seven simulated days twice. The entity inventory
snapshot in this file makes new per-zone entities a reviewable diff.

Larger histories use a base64-encoded zlib payload under `attempts_zlib` in the
existing per-growspace store. Small histories retain their readable `attempts`
array. Both forms decode through the existing whole-record validation; corrupt
or oversized compressed histories fail closed without overwriting the file.
The reusable compressed prefix contains only closed attempts. Requests and
charges update the tail, and a pruned or corrected prefix resets the stream.
No evidence, timestamps, readbacks or charged rows are dropped to fit the budget.
