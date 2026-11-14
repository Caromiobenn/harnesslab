import importlib.util
import json
from pathlib import Path

import pytest

from harnesslab.coding.config import save_json


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
            save_json(
                folder / f"{group}.outcome.json",
                {
                    "network_mode": mode,
                    "task": "task",
                    "group": group,
                    "repeat": 0,
                    "reward": 0,
                    "pipeline_ok": False,
                    "cleanup_verified": True,
                    "langsmith": {"feedback_status": "verified"},
                    "metrics": {
                        "model_responses": 2,
                        "model_issued_tool_calls": 1,
                        "agent_seconds": 2,
                        "trial_seconds": 3,
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
                },
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
    "change", ["missing", "duplicate", "metrics", "langsmith", "protocol", "model"]
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
    elif change == "langsmith":
        row["langsmith"]["feedback_status"] = "pending"
        save_json(path, row)
    elif change == "protocol":
        study["configuration"]["repeats"] = 2
    else:
        study["model_profile"]["model"] = "different"
    with pytest.raises(ValueError):
        worker.pilot_gate(study)
