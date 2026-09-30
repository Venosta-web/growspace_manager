"""A portable document reads frozen facts and keeps unknowns explicit (#683)."""

from dataclasses import replace
import json

import pytest

from custom_components.growspace_manager.domain.grow_run import (
    RunMetadata,
    RunNotFinalized,
    RunNotFound,
    RunSnapshot,
    RunStatus,
    build_snapshot,
    export_run,
)
from tests.domain.test_grow_run_finalization import FINALIZED, _completed, _outcome


def _finalized():
    ledger = _completed(outcomes=(_outcome("p1", dry_weight=None),))
    run = ledger.runs[0]
    snapshot = build_snapshot(run, finalized_at=FINALIZED, growspace_name="Tent")
    return replace(
        ledger, runs=(replace(run, status=RunStatus.FINALIZED, snapshot=snapshot),)
    )


def test_export_reads_frozen_metadata_outcomes_and_all_metrics():
    ledger = _finalized()
    run = ledger.runs[0]
    document = export_run(ledger, run.run_id)
    changed = replace(
        run, metadata=RunMetadata.create(label="Edited later"), harvest_outcomes=()
    )
    assert export_run(replace(ledger, runs=(changed,)), run.run_id) == document
    snapshot = document["snapshot"]
    assert snapshot["metadata"]["label"] == "Autumn"
    assert snapshot["harvest_outcomes"][0]["metrics"]["dry_weight"] is None
    assert snapshot["metrics"][0]["value"] is None
    assert snapshot["metrics"][0]["definition_version"] == 1
    assert snapshot["coverage"]
    assert json.loads(json.dumps(document)) == document
    assert RunSnapshot.from_dict(snapshot).as_dict() == snapshot
    # A caller changing the exported document or a source outcome cannot change it.
    snapshot["harvest_outcomes"][0]["metrics"]["dry_weight"] = 999
    run.harvest_outcomes[0].metrics["dry_weight"] = 888
    assert (
        export_run(ledger, run.run_id)["snapshot"]["harvest_outcomes"][0]["metrics"][
            "dry_weight"
        ]
        is None
    )


def test_an_older_snapshot_exports_unknown_metadata_and_outcomes_without_guessing():
    ledger = _finalized()
    run = ledger.runs[0]
    wire = run.snapshot.as_dict()
    del wire["metadata"]
    del wire["harvest_outcomes"]
    old = replace(run, snapshot=RunSnapshot.from_dict(wire))
    snapshot = export_run(replace(ledger, runs=(old,)), run.run_id)["snapshot"]
    assert snapshot["metadata"] is None
    assert snapshot["harvest_outcomes"] is None
    assert snapshot["metrics"] == wire["metrics"]


@pytest.mark.parametrize(
    "status", [RunStatus.ACTIVE, RunStatus.COMPLETED, RunStatus.VOIDED]
)
def test_only_finalized_runs_export(status):
    ledger = _finalized()
    ledger = replace(ledger, runs=(replace(ledger.runs[0], status=status),))
    with pytest.raises(RunNotFinalized) as error:
        export_run(ledger, ledger.runs[0].run_id)
    assert error.value.code == "grow_run.not_finalized"
    assert error.value.current_revision == ledger.revision


def test_unknown_run_refuses_export():
    with pytest.raises(RunNotFound):
        export_run(_finalized(), "missing")


@pytest.mark.parametrize(
    "field,value",
    [("metadata", []), ("harvest_outcomes", {}), ("harvest_outcomes", [{}])],
)
def test_malformed_frozen_export_facts_are_refused_on_load(field, value):
    wire = _finalized().runs[0].snapshot.as_dict()
    wire[field] = value
    with pytest.raises((TypeError, ValueError)):
        RunSnapshot.from_dict(wire)
