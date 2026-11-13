"""Protect N=1 reuse, failure attribution, and frozen budgets across continuation plans."""

import importlib.util
import json
from pathlib import Path

import pytest

script = Path(__file__).resolve().parents[1] / "scripts/plan_coding_continuation.py"
spec = importlib.util.spec_from_file_location("plan_coding_continuation", script)
planner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(planner)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


@pytest.fixture
def study(tmp_path):
    config = {
        "tasks": ["task"],
        "groups": ["mini", "deepagents_default"],
        "repeats": 1,
        "reasoning_effort": "high",
        "max_model_calls": 500,
        "network_mode": "offline",
    }

    def batch(name, **changes):
        plan = {
            "configuration": {**config, **changes},
            "model": "pinned-model",
            "base_url": "https://model.example/v1",
            "api_style": "aliyun",
            "thinking_body": {"enable_thinking": True},
            "source_hashes": {"src/actor.py": "fixture"},
            "tasks": [
                {
                    "task": "task",
                    "path": "/fixture/task",
                    "agent_seconds": 900,
                    "source_fingerprint": "same-template",
                }
            ],
        }
        folder = tmp_path / "artifacts/coding" / name
        save(folder / "plan.json", plan)
        return folder

    def outcome(folder, group="mini", reward=None, pipeline=False, exception=None, submission=None):
        row = {
            "task": "task",
            "group": group,
            "repeat": 0,
            "network_mode": "offline",
            "job_name": f"{folder.name}-{group}",
            "reward": reward,
            "pipeline_ok": pipeline,
            "exception": exception,
            "cleanup_verified": True,
            "metrics": {"submission": submission},
        }
        save(folder / f"{group}.outcome.json", row)
        return row

    return tmp_path, config, batch, outcome


def test_zero_score_is_kept_and_only_proven_cleanup_failure_is_replaceable(study):
    root, config, batch, outcome = study
    folder = batch("first")
    outcome(folder, reward=0, pipeline=True, exception={"exception_type": "AgentTimeoutError"})
    outcome(
        folder,
        group="deepagents_default",
        exception={
            "exception_type": "RuntimeError",
            "exception_message": "Actor processes did not exit",
        },
    )
    plan = planner.make_plan(root, config, ["first", "not-yet-created"])
    assert plan["planned_cells"] == 4
    assert plan["decision_counts"] == {
        "retain_scored": 1,
        "replace_after_shutdown_fix": 1,
        "not_started": 2,
    }
    assert plan["execution_authorized_by_this_file"] is False


def test_scored_review_error_cannot_be_resampled(study):
    root, config, batch, outcome = study
    outcome(batch("first"), reward=0, pipeline=False)
    plan = planner.make_plan(root, config, ["first"])
    assert plan["decision_counts"]["retain_score_review_pipeline"] == 1


def test_saved_submission_is_considered_before_another_model_call(study):
    root, config, batch, outcome = study
    outcome(
        batch("first"),
        exception={
            "exception_type": "RuntimeError",
            "exception_message": "Actor processes did not exit",
        },
        submission={"sha256": "saved"},
    )
    plan = planner.make_plan(root, config, ["first"])
    assert plan["decision_counts"]["inspect_saved_submission_for_regrade"] == 1


def test_duplicate_scores_are_rejected_even_when_one_pipeline_failed(study):
    root, config, batch, outcome = study
    outcome(batch("first"), reward=0, pipeline=False)
    outcome(batch("second"), reward=1, pipeline=True)
    with pytest.raises(ValueError, match="Multiple scored attempts"):
        planner.make_plan(root, config, ["first", "second"])


@pytest.mark.parametrize("change", ["reasoning", "model", "budget"])
def test_protocol_model_and_deadline_changes_require_separate_studies(study, change):
    root, config, batch, _ = study
    batch("first")
    folder = batch("second")
    path = folder / "plan.json"
    data = json.loads(path.read_text())
    if change == "reasoning":
        data["configuration"]["reasoning_effort"] = "max"
    elif change == "model":
        data["model"] = "different-snapshot"
    else:
        data["tasks"][0]["agent_seconds"] = 1800
    save(path, data)
    with pytest.raises(ValueError, match="changed"):
        planner.make_plan(root, config, ["first", "second"])


def test_unfinished_stage_is_not_mistaken_for_a_failed_sample(study):
    root, config, batch, _ = study
    folder = batch("first")
    save(
        folder / "first-mini.config.json",
        {
            "agents": [{"kwargs": {"experiment": config}}],
            "tasks": [{"path": "/fixture/task"}],
        },
    )
    plan = planner.make_plan(root, config, ["first"])
    assert plan["decision_counts"]["wait_or_inspect_unfinished"] == 1


def test_replacement_keeps_the_failed_attempt_and_selects_the_single_official_score(study):
    root, config, batch, outcome = study
    outcome(
        batch("first"),
        exception={
            "exception_type": "RuntimeError",
            "exception_message": "Actor processes did not exit",
        },
    )
    outcome(batch("replacement"), reward=0, pipeline=True)
    plan = planner.make_plan(root, config, ["first", "replacement"])
    cell = next(
        row for row in plan["cells"] if row["network"] == "offline" and row["group"] == "mini"
    )
    assert len(cell["attempts"]) == 2
    assert cell["decision"] == "retain_scored"
    assert "replacement" in cell["selected_outcome"]
