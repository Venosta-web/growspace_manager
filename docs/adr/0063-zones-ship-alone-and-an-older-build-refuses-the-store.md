# Zones Ship Alone, and an Older Build Refuses the Store Rather Than Rewrite It

**Status:** Accepted — not yet implemented (amends [ADR-0057](./0057-an-irrigation-zone-owns-its-cells-and-every-growspace-starts-with-one.md) decision 6)

The irrigation decisions in ADR-0054 to ADR-0062 change behaviour for people who configure nothing new (#863). The daily caps survive a restart. A pump found ON with our attempt still open is switched off. Manual Runs stop training. A running shot is no longer cancelled by the next request. A flat probe becomes `probe_unresponsive` and holds. And every growspace migrates, one way, into an implicit `default` zone.

Four facts about how this reaches a user shape the answer.

- **Every merge to `prerelease` is already a release.** It publishes a beta tag. A stable release comes only from `main`, and the last one, v1.2.3, is 125 commits behind `prerelease`, carrying none of ADR-0049 to ADR-0055.
- **A downgrade today loses the zones, not only the watering.** The models are mashumaro dataclasses, which ignore unknown keys. An older build loads a migrated store, drops `irrigation_zones`, and writes the store back without them on its first save. ADR-0057 decision 6 said a downgrade "finds no schedule or strategy and stops automatic irrigation". It also deletes the configuration the re-upgrade would have needed.
- **Home Assistant's `Store` already refuses a newer major version.** A build whose store is version 1 raises `UnsupportedStorageVersionError` on a version 2 document and fails setup. A newer _minor_ version is read as it is. The growspace store is 1.1 and has no migrate function.
- **Repairs issues have meant "there is something for you to do".** `exhaust_migration`, `ec_ramp_migration` and `irrigation_cap_migration` each raise a create-or-clear issue only when the grower must act.

1. **Two stable releases, and the zones ship alone.**
   - **1.3.0** promotes `prerelease` as it stands, plus the rest of ADR-0054 and ADR-0055 and ADR-0056. Every change in it is a two-way door: a new store an older build ignores, or a rule an older build simply does not apply.
   - **1.4.0** is the zone release: ADR-0057 to ADR-0062. The migration is the only one-way door in this map, and 0058 to 0062 all stand on zones, so none of them can ship earlier.
   - **The cut-off:** `prerelease` is promoted to 1.3.0 **before any ADR-0057 migration PR merges**, because a merge to `prerelease` is itself a beta. The implementation ticket for the migration is blocked by a "release 1.3.0" ticket when it is filed.
   - **2.0.0 stays reserved for removing `print_label`**, so the zone release and that removal never share a version, and a regression in either is attributable. Semver describes the API, and every existing call and entity keeps working through 1.4.0; the one-way door is in the store, and the store's own version records it.
2. **An older build refuses the store rather than rewriting it.** The growspace store moves to **major version 2**, and the zone migration runs in the `Store`'s own migrate function instead of in `Growspace.from_dict`. An older build then fails setup with `UnsupportedStorageVersionError`: loud, toward no water, and with nothing lost. Re-upgrading restores every zone. This is [[Store Containment]]'s rule, that a newer store is never rewritten by an older reader, achieved with the only tool an already-released build has.
3. **Every major migration keeps a [[Pre-Migration Copy]].** Before its first save at a new major version, a Growspace Manager store writes the untouched old document as `<key>.v<old major>`, here `growspace_manager.config.v1`, since the growspace store's key is `growspace_manager.config`.
   - It is written once, never updated, and never read by the integration.
   - It is kept indefinitely. It is a few kilobytes, and a rollback only works while it exists.
   - A later major migration writes its own copy beside it.

   A rollback is: stop Home Assistant, copy `growspace_manager.config.v1` over `growspace_manager.config`, install the older version, start. That needs no whole Home Assistant backup, which would also roll back every other integration's history.

4. **No opt-ins, and no Repairs issue just to announce.** Every change in both releases applies to existing installs.
   - The caps surviving a restart, the crash switch-off, Manual Runs not training, and the queue not cancelling a running shot are safety or accuracy fixes, and an opt-out would be an opt-out of the fix.
   - `zone_required` can only happen after a grower adds a second zone. `envelope_exceeded` cannot happen on an install that had no zones.
   - The changes that withhold water announce themselves through their own alerts, at the moment they matter.
   - **`probe_unresponsive` is enforced from its first release.** A pulled probe that still reports a steady value fires a shot every interval until the cap today, and that is the failure the check exists for. A false positive costs a paged hold the grower clears with a look at the probe and a Manual Run. A watch-only release would leave the flooding case open for a whole release.
   - `degraded_fallback` starts on `hold` for every zone (ADR-0062), so the replay changes nothing on upgrade.
5. **Where the notes live.**
   - **The changelog line is part of the implementing PR.** Each PR that changes behaviour for an unchanged configuration adds its line under `### Changed` in `CHANGELOG.md` when it lands, not at release time, so a behaviour change cannot ship without its note. The already merged #852, #857, #858 and the fix for #855 get theirs with 1.3.0.
   - **1.4.0 gets `docs/upgrading/zones.md`**, following `docs/deprecations/print-label.md`: what migrates, what `zone_required` means, and the rollback with the Pre-Migration Copy.
   - **Each stable release body** opens with a line linking its changelog section, and for 1.4.0 the upgrading guide, above the generated PR list.
6. **A migration that produces the wrong shape fails closed for that growspace only.** After migrating, each growspace is checked:
   - it has at least one zone, and a migrated one has exactly the `default` zone;
   - every cell belongs to exactly one zone;
   - every zone-owned field has moved, and no growspace-level copy is left behind.

   A growspace that fails is held under a latched [[Fault]], **`zone_migration_invalid`**, on its irrigation only, with a Repairs issue naming the growspace and the Pre-Migration Copy. Everything else keeps running, including that growspace's plants and climate. Unlike a pump Fault, it clears itself when the growspace passes the check again, on a load or after a zone edit, because its cause is the stored data and the data being right is the whole recovery. An unreadable Delivery Attempt store already fails closed as `delivery_record_unreadable` (ADR-0055) and needs nothing new.

7. **Upgrade tests.**
   - **In CI:** a golden pre-zones `.storage` document, written by v1.2.3 from a growspace with crop steering, a schedule, tanks and a moisture probe, anonymised, in `tests/fixtures/upgrade/`. Loaded through the `Store` migration, it must give a valid version 2 document whose `default` zone holds every moved field, unchanged entity unique_ids, a Pre-Migration Copy equal to the input, and **identical verdicts** from a steering tick and a schedule tick before and after.
   - **Before 1.4.0 is cut:** the same assertions live on the `ha-test` instance (:8124), by a hub script `./scripts/backend-hacs-update` in `card-hacs-update`'s mould: install v1.2.3 through HACS, provision, update to the candidate, check. It is a release-checklist step, not CI.

## Considered Options

- **One stable release with everything.** A regression in the migration would be indistinguishable from one in the caps or the attempts, and the two-way doors would wait on the one-way one.
- **A stable release per ADR.** 0058 to 0062 cannot ship without zones.
- **Accept the downgrade as ADR-0057 wrote it.** It is not "stops watering"; it deletes the zones on the first save.
- **A minor version bump.** An older build reads a newer minor version as it is, which is exactly the silent rewrite.
- **A Pre-Migration Copy only, without the major bump.** The copy survives, but the older build still rewrites the live store, and the grower learns about it from a tent that stopped watering.
- **A Repairs issue announcing the changes.** A Repairs issue with nothing to repair teaches growers to dismiss them, and the three that exist all ask for an action.
- **A watch-only first release for `probe_unresponsive`, or an opt-in.** Leaves the pulled-probe flood open for a release to spare a false positive that already announces itself.
- **Fail the whole integration on an invalid migration.** Takes plants, climate and labels down for a problem in one growspace's irrigation.
- **Upgrade tests in CI only, or on `ha-test` only.** CI cannot prove a real HACS update, and `ha-test` is too slow to gate every PR.
- **Ship zones as 2.0.0.** Couples them to the `print_label` removal, and the API does not break.

## Consequences

- ADR-0057 decision 6 is amended: the migration runs in the `Store` migrate function to version 2, and a downgrade refuses setup instead of stopping irrigation and losing the zones.
- `Store` users in this integration gain a rule: a major version bump writes a Pre-Migration Copy first.
- The version 2 migration also backfills ADR-0065: every recipe gets `revision: 1`, and every stamp an Applied Recipe copying its recipe's current values.
- 1.3.0 has to be cut before the migration work merges, and the map's Notes carry that cut-off.
- `CHANGELOG.md`'s `[1.2.3] - Unreleased` heading is stale and is corrected when the 1.3.0 section is written.
- The hub gains `./scripts/backend-hacs-update`, and the backend gains `tests/fixtures/upgrade/`.
