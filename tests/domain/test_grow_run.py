"""The Run Ledger's rules, with plain values only (#668)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from typing import Any

import pytest

from custom_components.growspace_manager.domain.grow_run import (
    CODE_ALREADY_ACTIVE,
    CODE_REVISION_CONFLICT,
    WARNING_PLANTS_PRESENT,
    BaselineState,
    GrowRun,
    OpeningBaseline,
    PlantMovementFact,
    PresentPlant,
    RunAcknowledgementRequired,
    RunAlreadyActive,
    RunCommand,
    RunLedger,
    RunMetadata,
    RunParticipation,
    RunRevisionConflict,
    RunStatus,
    preview_completion,
    run_details,
    run_summary,
    sensor_state,
)
from custom_components.growspace_manager.websocket.grow_runs import refusal_result

STARTED = datetime(2026, 7, 24, 20, 30, tzinfo=UTC)
CONTRACT = Path(__file__).parents[1] / "fixtures" / "contract"
REGENERATE = (
    ".venv/bin/pytest tests/domain/test_grow_run.py --regenerate-contract-fixture"
)
BASELINE = OpeningBaseline(
    conditions=(BaselineState("binary_sensor.tent_mold_risk", "mold_risk", "on"),),
    equipment=(BaselineState("switch.tent_pump", "switch", "off"),),
)


def _start(
    ledger: RunLedger,
    *,
    expected: int | None = None,
    plants: tuple[str, ...] = ("p1", "p2"),
    now: datetime = STARTED,
    run_id: str = "run-1",
    label: str | None = "Autumn",
) -> tuple[RunLedger, GrowRun]:
    return ledger.start(
        expected_revision=ledger.revision if expected is None else expected,
        run_id=run_id,
        command_id=f"cmd-{run_id}",
        now=now,
        timezone="Europe/Berlin",
        metadata=RunMetadata.create(label=label, tags=["organic"], goals="Beat #3"),
        baseline=BASELINE,
        plant_ids=plants,
        actor_user_id="user-1",
    )


def test_start_assigns_every_field_of_an_active_run() -> None:
    ledger, run = _start(RunLedger("tent"))

    assert run.run_id == "run-1"
    assert run.growspace_id == "tent"
    assert run.sequence_number == 1
    assert run.status is RunStatus.ACTIVE
    assert run.timezone == "Europe/Berlin"
    assert run.started_at == STARTED
    assert run.metadata == RunMetadata("Autumn", ("organic",), "Beat #3", None)
    assert run.baseline == BASELINE
    assert [(p.plant_id, p.opened_at, p.closed_at) for p in run.participations] == [
        ("p1", STARTED, None),
        ("p2", STARTED, None),
    ]
    (audit,) = run.audit
    assert (audit.command, audit.command_id, audit.actor_user_id) == (
        RunCommand.START,
        "cmd-run-1",
        "user-1",
    )
    assert (audit.prior_revision, audit.resulting_revision) == (0, 1)
    assert (ledger.revision, ledger.next_sequence, ledger.active_run) == (1, 2, run)


def test_an_empty_growspace_starts_a_run_with_no_participants() -> None:
    _, run = _start(RunLedger("tent"), plants=())
    assert run.participations == ()
    assert run.participant_count == 0


def test_a_plant_listed_twice_participates_once() -> None:
    _, run = _start(RunLedger("tent"), plants=("p1", "p1"))
    assert run.participant_count == 1


def test_a_stale_revision_is_refused_with_the_current_one() -> None:
    ledger, run = _start(RunLedger("tent"))

    with pytest.raises(RunRevisionConflict) as refused:
        _start(ledger, expected=0, run_id="run-2")

    assert refused.value.code == CODE_REVISION_CONFLICT
    assert refused.value.current_revision == 1
    assert refused.value.active_run == run


def test_a_second_active_run_is_refused() -> None:
    ledger, run = _start(RunLedger("tent"))

    with pytest.raises(RunAlreadyActive) as refused:
        _start(ledger, run_id="run-2")

    assert refused.value.code == CODE_ALREADY_ACTIVE
    assert (refused.value.current_revision, refused.value.active_run) == (1, run)


def test_sequence_numbers_come_from_the_ledger_not_from_its_runs() -> None:
    """A discarded Run's number is never issued again (#673 will discard)."""
    ledger = RunLedger("tent", revision=5, next_sequence=4)
    _, run = _start(ledger)
    assert run.sequence_number == 4


def test_local_days_count_calendar_days_in_the_run_timezone() -> None:
    _, run = _start(RunLedger("tent"))  # 22:30 local on 24 July
    assert run.local_days(STARTED + timedelta(hours=1)) == 0
    assert run.local_days(STARTED + timedelta(hours=2)) == 1  # 00:30 on the 25th
    assert run.local_days(STARTED + timedelta(days=60, hours=2)) == 61


def test_metadata_is_trimmed_and_blank_means_absent() -> None:
    metadata = RunMetadata.create(
        label="  ", tags=[" a ", "a", "", "b"], goals=" g ", notes=None
    )
    assert metadata == RunMetadata(None, ("a", "b"), "g", None)


@pytest.mark.parametrize(
    "arguments",
    [
        {"label": "x" * 81},
        {"goals": "x" * 2001},
        {"tags": ["x" * 41]},
        {"tags": [f"t{i}" for i in range(21)]},
    ],
)
def test_metadata_past_its_bounds_is_refused(arguments: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        RunMetadata.create(**arguments)


def test_a_ledger_survives_its_durable_form() -> None:
    ledger, _ = _start(RunLedger("tent"))
    assert RunLedger.from_dict(json.loads(json.dumps(ledger.as_dict()))) == ledger


def test_participation_and_fact_reject_corrupt_intervals_and_flags() -> None:
    """Corruption cannot silently change half-open intervals or outbox state."""
    with pytest.raises(ValueError, match="closes before"):
        RunParticipation.from_dict(
            {
                "plant_id": "p1",
                "opened_at": STARTED.isoformat(),
                "closed_at": (STARTED - timedelta(seconds=1)).isoformat(),
            }
        )
    with pytest.raises(TypeError, match="not boolean"):
        PlantMovementFact.from_dict(
            {
                "fact_id": "f1",
                "plant_id": "p1",
                "at": STARTED.isoformat(),
                "kind": "entry",
                "source_growspace_id": None,
                "target_growspace_id": "tent",
                "source_run_id": None,
                "target_run_id": "run-1",
                "projected": "yes",
            }
        )


def test_duplicate_open_intervals_and_movement_ids_are_refused() -> None:
    """A damaged Run cannot inflate participation or replay one movement twice."""
    document = _stored()
    document["runs"][0]["participations"].append(
        document["runs"][0]["participations"][0]
    )
    with pytest.raises(ValueError, match="more than one open"):
        RunLedger.from_dict(document)

    wire = _wire_forms()["grow_run_details_v1"]
    document = _stored()
    document["runs"][0]["movement_history"] = [wire["run"]["movement_history"][0]] * 2
    with pytest.raises(ValueError, match="appears twice"):
        RunLedger.from_dict(document)


def _stored() -> dict[str, Any]:
    ledger, _ = _start(RunLedger("tent"))
    return json.loads(json.dumps(ledger.as_dict()))


def _mutate(path: str, value: Any) -> dict[str, Any]:
    document = _stored()
    *parents, leaf = path.split(".")
    node: Any = document
    for part in parents:
        node = node[int(part)] if part.isdigit() else node[part]
    if isinstance(node, list):
        node[int(leaf)] = value
    else:
        node[leaf] = value
    return document


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("growspace_id", ""),
        ("revision", -1),
        ("revision", "1"),
        ("next_sequence", 1),  # the stored Run already holds #1
        ("runs", {}),
        ("runs.0", None),
        ("runs.0.growspace_id", "other"),
        ("runs.0.status", "paused"),
        ("runs.0.timezone", "Mars/Olympus"),
        ("runs.0.started_at", "2026-07-24T20:30:00"),
        ("runs.0.metadata", []),
        ("runs.0.metadata.tags", None),
        ("runs.0.metadata.tags", [""]),
        ("runs.0.metadata.label", 3),
        ("runs.0.baseline", None),
        ("runs.0.baseline.conditions", None),
        ("runs.0.baseline.equipment.0", "switch.x"),
        ("runs.0.baseline.equipment.0.state", None),
        ("runs.0.participations", None),
        ("runs.0.participations.0", []),
        ("runs.0.participations.0.closed_at", 5),
        ("runs.0.audit", None),
        ("runs.0.audit.0", None),
        ("runs.0.audit.0.command", "resume"),
        ("runs.0.audit.0.resulting_revision", 0),
        ("runs.0.audit.0.actor_user_id", 1),
    ],
)
def test_a_malformed_ledger_is_refused_whole(path: str, value: Any) -> None:
    with pytest.raises((TypeError, ValueError)):
        RunLedger.from_dict(_mutate(path, value))


def test_a_stored_ledger_with_two_active_runs_is_refused() -> None:
    document = _stored()
    twin = {**document["runs"][0], "run_id": "run-2", "sequence_number": 2}
    document["runs"].append(twin)
    document["next_sequence"] = 3
    with pytest.raises(ValueError, match="more than one Active Run"):
        RunLedger.from_dict(document)


def test_a_non_object_ledger_is_refused() -> None:
    with pytest.raises(TypeError):
        RunLedger.from_dict([])


# ---------------------------------------------------------------------------
# Wire forms the card parses (contract fixtures)
# ---------------------------------------------------------------------------


def _wire_forms() -> dict[str, Any]:
    empty = RunLedger("tent", revision=3, next_sequence=4)
    ledger, run = _start(empty)
    now = STARTED + timedelta(days=60, hours=2)
    active_state, active_attributes = sensor_state(ledger, now)
    none_state, none_attributes = sensor_state(empty, now)
    try:
        _start(ledger, expected=3, run_id="run-2")
    except RunRevisionConflict as refused:
        refusal = refusal_result(refused)
    moved = ledger.project_movement(
        PlantMovementFact(
            fact_id="fact-1",
            plant_id="p1",
            at=STARTED + timedelta(days=7),
            kind="transplant",
            source_growspace_id="tent",
            target_growspace_id="other",
            source_run_id="run-1",
            target_run_id=None,
        )
    )
    projected_run = moved.active_run
    assert projected_run is not None
    ended = STARTED + timedelta(days=70)
    harvested = moved.project_movement(
        PlantMovementFact(
            fact_id="fact-2",
            plant_id="p2",
            at=STARTED + timedelta(days=63),
            kind="harvest",
            source_growspace_id="tent",
            target_growspace_id="dry",
            source_run_id="run-1",
            target_run_id=None,
        )
    ).project_movement(
        PlantMovementFact(
            fact_id="fact-3",
            plant_id="p3",
            at=STARTED + timedelta(days=64),
            kind="entry",
            source_growspace_id=None,
            target_growspace_id="tent",
            source_run_id=None,
            target_run_id="run-1",
        )
    )
    preview = preview_completion(
        harvested,
        now=ended,
        plants_present=[
            PresentPlant("p3", "OG Kush", "Pheno #1", "flower"),
            PresentPlant("p4", "Amnesia", "", "veg"),
        ],
        dry_weights={"p2": None, "p3": None, "p4": None},
        pending_facts=(),
        delivering_outputs=("switch.tent_pump",),
        retrospective_note="Dense buds, slow dry",
    )
    try:
        harvested.complete(
            expected_revision=harvested.revision,
            run_id="run-1",
            preview=replace(preview, delivering_outputs=()),
            acknowledged=[WARNING_PLANTS_PRESENT],
            command_id="cmd-complete",
            actor_user_id="user-1",
        )
    except RunAcknowledgementRequired as refused:
        unacknowledged = refusal_result(refused)
    completed_ledger, completed = harvested.complete(
        expected_revision=harvested.revision,
        run_id="run-1",
        preview=replace(preview, delivering_outputs=()),
        acknowledged=list(preview.warnings),
        command_id="cmd-complete",
        actor_user_id="user-1",
    )
    return {
        "active_run_sensor_v1": {
            # As Home Assistant publishes them: the state is always a string.
            "active": {"state": str(active_state), "attributes": active_attributes},
            "none": {"state": str(none_state), "attributes": none_attributes},
        },
        "grow_run_started_v1": {
            "outcome": "started",
            "run_revision": ledger.revision,
            "active_run": run_summary(run, ledger.revision),
        },
        "grow_run_refused_v1": refusal,
        "grow_run_details_v1": run_details(projected_run, moved.revision),
        "grow_run_completion_preview_v1": {
            "outcome": "preview",
            "preview": preview.as_dict(),
        },
        "grow_run_completed_v1": {
            "outcome": "completed",
            "run_revision": completed_ledger.revision,
            "run": run_summary(completed, completed_ledger.revision),
        },
        "grow_run_completion_refused_v1": unacknowledged,
        "grow_run_completed_details_v1": run_details(
            completed, completed_ledger.revision
        ),
    }


@pytest.mark.parametrize("name", sorted(_wire_forms()))
def test_contract_fixture(name: str, pytestconfig: pytest.Config) -> None:
    """Each wire form the card parses is exactly the committed fixture."""
    wire = _wire_forms()[name]
    path = CONTRACT / f"{name}.json"
    if pytestconfig.getoption("regenerate_contract_fixture"):
        path.write_text(f"{json.dumps(wire, indent=2, sort_keys=True)}\n")
    assert path.exists(), f"{name} is missing; regenerate with: {REGENERATE}"
    assert wire == json.loads(path.read_text()), (
        f"{name} changed; review the diff, then regenerate with: {REGENERATE}"
    )


def test_the_sensor_keeps_one_attribute_set_whatever_its_state() -> None:
    forms = _wire_forms()["active_run_sensor_v1"]
    assert forms["active"]["state"] == "4"
    assert forms["active"]["attributes"]["duration_days"] == 61
    assert forms["none"]["state"] == "none"
    assert forms["none"]["attributes"]["run_revision"] == 3
    assert set(forms["active"]["attributes"]) == set(forms["none"]["attributes"])
