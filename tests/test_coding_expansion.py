import importlib.util
import json
from pathlib import Path

import pytest

from harnesslab.coding.config import save_json
from harnesslab.coding.observability import measurements
from harnesslab.coding.reuse import digest


def script(name):
    path = Path(__file__).parents[1] / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_long_tasks_split_groups_without_duplicating_or_dropping_cells():
    builder = script("prepare_coding_expansion.py")
    groups = ["mini", "deepagents_default", "generic_retry", "rubric_transcript", "rubric_evidence"]
    rows = [
        {"task": "long", "agent_seconds": 12000, "verifier_seconds": 12000, "build_seconds": 600}
    ]
    units = builder.execution_units(rows, groups)
    cells = [(unit["network"], group) for unit in units for group in unit["groups"]]
    assert len(cells) == len(set(cells)) == 10
    assert all(unit["timeout_bound_seconds"] <= 43200 for unit in units)
    with pytest.raises(ValueError, match="wall-time"):
        builder.execution_units(rows, groups, wall_seconds=3600)


@pytest.fixture
def prior_batches(tmp_path):
    builder = script("prepare_coding_expansion.py")
    full = {
        "tasks": ["pilot", "first", "second", "next"],
        "groups": ["mini", "deepagents_default"],
        "repeats": 1,
        "reasoning_effort": "high",
    }
    profile = {"model": "fixed", "thinking_body": {"reasoning_effort": "high"}}
    selection = {"pilot_tasks": ["pilot"], "pilot_batches": ["pilot-output"], "prior_studies": []}
    for task, preceding in [("first", []), ("second", ["first"])]:
        root = tmp_path / task
        root.mkdir()
        (root / "source.py").write_text("frozen runtime\n")
        path = root / "study.json"
        save_json(
            path,
            {
                "run": task,
                "configuration": full,
                "model_profile": profile,
                "pilot_tasks": selection["pilot_tasks"],
                "pilot_batches": selection["pilot_batches"],
                "ready_tasks": [task],
                "reserved_prior_tasks": preceding,
                "source_hashes": {"source.py": digest(root / "source.py")},
                "script_hashes": {},
                "new_model_cells": 4,
                "units": [
                    {"task": task, "network": mode, "groups": full["groups"]}
                    for mode in ["offline", "public"]
                ],
            },
        )
        selection["prior_studies"].append(
            {"root": str(root), "study": "study.json", "sha256": digest(path)}
        )
    return builder, full, profile, selection, tmp_path


def test_followup_expansion_reserves_prior_cells_and_freezes_their_plans(prior_batches):
    builder, full, profile, selection, root = prior_batches
    reserved, snapshots = builder.prior_reservations(
        full, selection, profile, root / "next", {"next"}
    )
    assert reserved == {"first", "second"}
    assert sum(row["model_cells"] for row in snapshots) == 8
    assert set(full["tasks"]) - reserved - set(selection["pilot_tasks"]) == {"next"}
    for row in snapshots:
        assert Path(row["snapshot"]).read_bytes() == Path(row["origin"]).read_bytes()
        assert digest(Path(row["snapshot"])) == row["sha256"]


@pytest.mark.parametrize(
    "change",
    [
        "resample",
        "model",
        "protocol",
        "source",
        "missing_ancestor",
        "duplicate_cell",
        "missing_cell",
    ],
)
def test_followup_expansion_rejects_duplicate_or_incompatible_reservations(prior_batches, change):
    builder, full, profile, selection, root = prior_batches
    selected = {"next"}
    if change == "resample":
        selected = {"first"}
    elif change == "model":
        profile = {**profile, "model": "different"}
    elif change == "protocol":
        full = {**full, "repeats": 2}
    elif change == "source":
        (root / "first/source.py").write_text("changed runtime\n")
    elif change == "missing_ancestor":
        selection["prior_studies"] = selection["prior_studies"][1:]
    else:
        reference = selection["prior_studies"][0]
        path = Path(reference["root"]) / reference["study"]
        saved = json.loads(path.read_text())
        if change == "duplicate_cell":
            saved["units"].append(saved["units"][0])
        else:
            saved["units"].pop()
        save_json(path, saved)
        reference["sha256"] = digest(path)
    with pytest.raises(ValueError):
        builder.prior_reservations(full, selection, profile, root / "next", selected)


@pytest.fixture
def pilot(tmp_path):
    worker = script("run_coding_expansion_unit.py")
    protocol = {name: 1 for name in worker.PROTOCOL_FIELDS}
    protocol["groups"] = ["mini", "deepagents_default"]
    profile = {
        "model": "fixture",
        "base_url": "https://fixture.invalid",
        "api_style": "fixture",
        "thinking_body": {},
    }
    batches = []
    for mode in ("offline", "public"):
        folder = tmp_path / mode
        batches.append(str(folder))
        save_json(folder / "plan.json", {"configuration": protocol, **profile})
        for group in protocol["groups"]:
            row = {
                "network_mode": mode,
                "task": "task",
                "group": group,
                "repeat": 0,
                "reward": 0,
                "pipeline_ok": False,
                "cleanup_verified": True,
                "trial": str(folder / "trials" / group),
                "langsmith": {"feedback_status": "uploaded"},
                "metrics": {
                    "model_responses": 2,
                    "model_issued_tool_calls": 1,
                    "agent_seconds": 2,
                    "trial_seconds": 3,
                    "environment_commands": 1,
                    "environment_command_failures": 0,
                    "submission_capture_seconds": 1,
                    "candidates": 1,
                    "evidence_checks": 0,
                    "tokens_and_lengths": {
                        key: 1
                        for key in (
                            "input_tokens",
                            "output_tokens",
                            "visible_text_chars",
                            "reasoning_text_chars",
                            "tool_argument_chars",
                        )
                    },
                },
            }
            save_json(folder / f"{group}.outcome.json", row)
            if group != "mini":
                save_json(
                    Path(row["trial"]) / "agent/langsmith-metrics.json",
                    {"verified": True, "measurements": measurements(row)},
                )
    return (
        worker,
        {
            "configuration": protocol,
            "model_profile": profile,
            "pilot_batches": batches,
            "pilot_tasks": ["task"],
        },
        tmp_path,
    )


def test_pilot_gate_preserves_valid_zeros_and_retains_unscored_setup_failures(pilot):
    worker, study, root = pilot
    row = json.loads((root / "offline/mini.outcome.json").read_text())
    row["reward"] = None
    save_json(root / "offline/setup-failure.outcome.json", row)
    gate = worker.pilot_gate(study)
    assert gate["ok"] and len(gate["preserved_cells"]) == 4
    assert all(row["reward"] == 0 for row in gate["preserved_cells"])
    assert len(gate["unscored_attempts_retained"]) == 1


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "duplicate",
        "metrics",
        "langsmith",
        "feedback_values",
        "missing_feedback",
        "protocol",
        "model",
    ],
)
def test_pilot_gate_stops_expansion_before_new_model_calls(pilot, change):
    worker, study, root = pilot
    path = root / "offline/deepagents_default.outcome.json"
    row = json.loads(path.read_text())
    if change == "missing":
        path.unlink()
    elif change == "duplicate":
        save_json(root / "offline/duplicate.outcome.json", row)
    elif change == "metrics":
        row["metrics"]["tokens_and_lengths"]["input_tokens"] = None
        save_json(path, row)
    elif change in ("langsmith", "feedback_values", "missing_feedback"):
        receipt_path = Path(row["trial"]) / "agent/langsmith-metrics.json"
        if change == "missing_feedback":
            receipt_path.unlink()
        else:
            receipt = json.loads(receipt_path.read_text())
            if change == "langsmith":
                receipt["verified"] = False
            else:
                receipt["measurements"] = {}
            save_json(receipt_path, receipt)
    elif change == "protocol":
        study["configuration"]["repeats"] = 2
    else:
        study["model_profile"]["model"] = "different"
    with pytest.raises(ValueError):
        worker.pilot_gate(study)
