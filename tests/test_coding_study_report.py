"""Official scores and integration errors use independent denominators."""

import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "coding_report", Path(__file__).resolve().parents[1] / "scripts/report_coding_study.py"
)
reporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reporter)


def outcome(root, batch, task, reward, pipeline, group="mini", tokens=10):
    folder = root / "artifacts/coding" / batch
    folder.mkdir(parents=True, exist_ok=True)
    row = {
        "task": task,
        "group": group,
        "repeat": 0,
        "network_mode": "offline",
        "job_name": f"{batch}-{task}-{group}",
        "pipeline_ok": pipeline,
        "reward": reward,
        "cleanup_verified": True,
        "trial": None,
        "metrics": {"tokens_and_lengths": {"output_tokens": tokens}},
    }
    (folder / f"{task}-{group}.outcome.json").write_text(json.dumps(row))


def test_scored_review_failure_stays_in_accuracy_and_unscored_cost_is_retained(tmp_path):
    config = {"tasks": ["ok", "review-error", "infrastructure"], "groups": ["mini"], "repeats": 1}
    outcome(tmp_path, "first", "ok", 1, True, tokens=10)
    outcome(tmp_path, "first", "review-error", 0, False, tokens=20)
    outcome(tmp_path, "first", "infrastructure", None, False, tokens=30)
    report = reporter.make_report(tmp_path, config, ["first"])
    group = next(row for row in report["groups"] if row["network"] == "offline")
    assert group["success_rate"] == 0.5
    assert group["valid_scored_cells"] == 2
    assert group["scored_pipeline_error_cells"] == 1
    assert group["infrastructure_error_cells"] == 1
    assert group["all_ended_attempt_usage"]["output_tokens"]["sum"] == 60


def test_cannot_pick_better_score_after_scored_pipeline_failure(tmp_path):
    config = {"tasks": ["task"], "groups": ["mini"], "repeats": 1}
    outcome(tmp_path, "first", "task", 0, False)
    outcome(tmp_path, "second", "task", 1, True)
    with pytest.raises(ValueError, match="Multiple official scores"):
        reporter.make_report(tmp_path, config, ["first", "second"])


def test_case_comparison_keeps_scored_errors_visible(tmp_path):
    config = {"tasks": ["task"], "groups": ["deepagents_default", "rubric_evidence"], "repeats": 1}
    outcome(tmp_path, "first", "task", 1, True, "deepagents_default")
    outcome(tmp_path, "first", "task", 0, False, "rubric_evidence")
    report = reporter.make_report(tmp_path, config, ["first"])
    assert report["case_candidates"][0]["label"] == "regression_to_inspect"
    assert report["case_candidates"][0]["treatment_pipeline_ok"] is False
