# Upgrading to Irrigation Zones in 1.4.0

1.4.0 ships Irrigation Zones, independent zone control and recipe revisions.
It applies to existing installations automatically. The Classic `print_label`
service remains available; its removal is reserved for **2.0.0**.

## Before updating

Update the Growspace Manager card first to a release that understands
`probe_unresponsive` and `zone_migration_invalid`. **v1.4.0-next.60** is the
first such release; enable beta releases in HACS to select that prerelease.
Keep a Home Assistant backup and check your probe placement and emitters.
No zone splitting or new valves are required for an existing pump-only setup.

## What migrates

On first start, `.storage/growspace_manager.config` moves from store major
version 1 to **2**. Each growspace gets one implicit zone, `default`, owning
all its grid cells. Its flow rate, schedule, soil trigger, minimum interval,
steering strategy and phase, substrate history and substrate probes move into
that zone. Existing entities retain their unique IDs. Plants, climate, tanks,
lights, dark gating and daily caps remain growspace-owned. Recipe revisions
start at 1 and existing stamps gain an Applied Recipe snapshot.

Before saving version 2, the integration keeps the untouched version 1 document
at **`.storage/growspace_manager.config.v1`**. This Pre-Migration Copy is written
once, kept indefinitely and never read automatically. It is not a rolling backup.

A single-zone setup continues with its existing settings. Each additional zone
owns its cells and exclusive valves and steers and schedules independently.
Zones share one supply queue and the growspace's daily caps. Other zones must
read closed, the selected valves must confirm open before supply ON, and supply
OFF must confirm before valves close. Output faults block the whole growspace.

## Recipes and hand tweaks

Recipe stamps now record the recipe’s revision and a copy of its portable,
zone-owned values. Editing the library reports **Recipe Updated** separately
from drift; only changes to the zone’s stamped values count as hand tweaks.
An untweaked zone with Program Auto-advance follows a newer revision on its
next refresh. Without auto-advance, the revision is available for manual apply.
Deleting a recipe leaves its applied copy available for drift comparison.

A schedule-recipe stamp no longer writes drains, drain duration, daily volume
caps, cycle limits or the dark-period gate, even in a single-zone growspace.
Set these directly on the growspace. Crop-steering stamps likewise leave the
lights-on time and automatic light tracking alone. Recipes keep these shared
settings as provenance and warn on a mismatch, without changing them.

Migration gives existing recipes revision 1 and copies the current recipe’s
zone-owned values into existing stamps. A recipe edited before migration may
therefore already read as drifted. A stamp naming a deleted recipe has no copy.

## What `zone_required` means

Once a growspace has two or more zones, a zone-scoped settings, strategy,
phase, schedule, recipe or irrigation command must name `zone_id`.
`zone_required` means the command omitted that selection; it is refused rather
than applied to an arbitrary zone. Select the intended zone in the card, or
add its ID to the automation or WebSocket request. Single-zone calls may still
omit it. Hand Watering remains growspace-scoped.

The supported envelope is six zones per growspace, eight valves per zone,
four substrate probes per quantity and ten irrigated growspaces. Repairs warns
about too many irrigated growspaces or shots that cannot fit their interval;
those warnings do not themselves stop watering.

## Holds and recovery

- **`probe_unresponsive`**: three confirmed steering shots without a moisture
  rise hold automatic shots immediately. Check both that the Control Probe is
  in the pot and that the emitter is dripping. The alert follows the sensor
  delay; Manual Runs remain available subject to the safety gates. Invalid
  control readings do not train adaptive control or fill dryback history.
- **Degraded Control**: a healthy witness with a learned offset may substitute
  for a failed Control Probe. Feedback and dryback recording pause. Fallback
  defaults to `hold`; only an explicit `degraded_fallback: replay` repeats
  compatible Reference Day shots at 80%, through the queue and safety gates.
- **`zone_migration_invalid`**: irrigation is held for the affected growspace,
  while its plants and climate keep running. Open **Settings → System → Repairs**
  for the growspace name, integrity problems and Pre-Migration Copy path.
  Correct the zone data through valid zone edits, or restore the old document
  using the rollback below. The hold clears when a load or zone edit validates
  the zones; pump-fault acknowledgement does not repair migration data.

## Rolling back

Larger Delivery Attempt histories in this release can also be stored as
losslessly compressed `attempts_zlib` data. An older build that reads Delivery
Attempts but does not support that form holds irrigation as
`delivery_record_unreadable`. The growspace `.v1` copy does not restore those
separate histories. If that hold appears after rollback, re-upgrade or restore
a compatible Delivery Attempt history from a suitable backup; do not erase the
ledger or its daily-cap charges to force watering.

An older build refuses the version 2 store with
`UnsupportedStorageVersionError`. Installing it alone does not restore the old
configuration, and it does not rewrite the newer store. Re-upgrading restores
access to the zones.

To restore the pre-upgrade configuration:

1. **Stop Home Assistant.** Do not copy storage while it is running.
2. Keep a separate copy of the current `.storage/growspace_manager.config` if
   you want to retain zone edits made since upgrading.
3. Copy `.storage/growspace_manager.config.v1` over
   `.storage/growspace_manager.config` in Home Assistant's configuration directory.
   Copy it; keep the `.v1` original.
4. Install the older integration release, then start Home Assistant.

Only the growspace configuration returns to the migration instant. Changes
made to it since then are absent; this does not roll back other integrations,
plant history or all Growspace Manager stores. If the `.v1` copy is missing,
restore a suitable backup rather than changing the document's version number.
