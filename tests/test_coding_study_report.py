"""Official scores and integration errors use independent denominators."""

import hashlib
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


def test_runtime_cohorts_preserve_errors_and_costs_in_their_original_adapter(tmp_path):
    config = {
        "tasks": ["legacy", "native", "error"],
        "groups": ["deepagents_default"],
        "repeats": 1,
    }
    for task, reward, tokens in [("legacy", 1, 10), ("native", 0, 20), ("error", None, 30)]:
        outcome(tmp_path, "first", task, reward, reward is not None, "deepagents_default", tokens)
        path = tmp_path / f"artifacts/coding/first/{task}-deepagents_default.outcome.json"
        row = json.loads(path.read_text())
        metadata = {"configuration": {"response_transport": "streaming"}}
        if task != "legacy":
            metadata.update(
                request_adapter="native_tool_images_v1",
                effective_model_profile={"max_input_tokens": 1000000},
            )
        row["agent_result"] = {"metadata": metadata}
        path.write_text(json.dumps(row))
    report = reporter.make_report(tmp_path, config, ["first"])
    cohorts = {row["request_adapter"]: row for row in report["runtime_cohorts"]}
    assert len(cohorts) == 2
    legacy, native = cohorts["legacy_sdk_tool_content"], cohorts["native_tool_images_v1"]
    assert legacy["success_rate"] == 1 and native["success_rate"] == 0
    assert legacy["effective_model_profile"] is None
    assert native["ended_attempts"] == 2 and native["valid_scored_cells"] == 1
    assert native["all_ended_attempt_usage"]["output_tokens"]["sum"] == 50
    assert report["groups"][0]["all_ended_attempt_usage"]["output_tokens"]["sum"] == 60


def test_mini_native_tooling_remains_visible_in_case_comparisons(tmp_path):
    config = {"tasks": ["task"], "groups": ["mini", "deepagents_default"], "repeats": 1}
    for group in config["groups"]:
        outcome(tmp_path, "first", "task", 1, True, group)
    report = reporter.make_report(tmp_path, config, ["first"])
    case = report["case_candidates"][0]
    assert case["base_request_adapter"] == "mini_native_shell"
    assert case["treatment_request_adapter"] == "legacy_sdk_tool_content"


@pytest.fixture
def regraded(tmp_path):
    config = {"tasks": ["task"], "groups": ["deepagents_default"], "repeats": 1}
    outcome(tmp_path, "first", "task", None, False, "deepagents_default", tokens=30)
    path = tmp_path / "artifacts/coding/first/task-deepagents_default.outcome.json"
    row = json.loads(path.read_text())
    row.update(
        exception={"exception_type": "OpenAITimeoutError"},
        agent_result={
            "metadata": {
                "started_model_calls": 4,
                "configuration": {"response_transport": "non_streaming"},
            }
        },
    )
    row["metrics"]["model_responses"] = 3
    path.write_text(json.dumps(row))
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"fixture":"unchanged submission"}')

    def sha(file):
        return hashlib.sha256(file.read_bytes()).hexdigest()

    trial = tmp_path / "regrade"
    (trial / "agent").mkdir(parents=True)
    (trial / "verifier").mkdir()
    (trial / "agent/regrade-provenance.json").write_text(
        json.dumps({"source_sha256": sha(manifest), "model_calls": 0})
    )
    (trial / "result.json").write_text(json.dumps({"verifier_result": {"rewards": {"reward": 0}}}))
    tests = {"tests": 9, "passed": 0, "failed": 9}
    (trial / "verifier/ctrf.json").write_text(json.dumps({"results": {"summary": tests}}))
    ledger = {
        "ok": True,
        "expected": 1,
        "outcomes": [
            {
                "cell": ["offline", "task", "deepagents_default", 0],
                "accepted": True,
                "model_calls": 0,
                "reward": 0,
                "ctrf_summary": tests,
                "source": {
                    "outcome": str(path),
                    "outcome_sha256": sha(path),
                    "manifest": str(manifest),
                    "manifest_sha256": sha(manifest),
                },
                "regrade": {"pipeline_ok": True, "cleanup_verified": True, "trial": str(trial)},
            }
        ],
    }
    ledger_path = tmp_path / "regrades.json"
    ledger_path.write_text(json.dumps(ledger))
    return config, path, ledger_path, ledger


def test_regrade_recovers_score_without_erasing_error_or_counting_another_attempt(
    tmp_path, regraded
):
    config, original, ledger_path, _ = regraded
    before = original.read_bytes()
    report = reporter.make_report(tmp_path, config, ["first"], [ledger_path])
    (row,) = report["trials"]
    assert row["reward"] == 0 and row["original_reward"] is None
    assert row["error_type"] == "OpenAITimeoutError" and row["pipeline_ok"] is False
    assert row["usage_completeness"] == "partial"
    group = next(g for g in report["groups"] if g["network"] == "offline")
    assert (
        group["valid_scored_cells"]
        == group["scored_pipeline_error_cells"]
        == group["regraded_cells"]
        == 1
    )
    assert group["all_ended_attempt_usage"]["output_tokens"]["sum"] == 30
    assert group["ended_attempts_including_replacements"] == 1
    assert original.read_bytes() == before


@pytest.mark.parametrize("change", ["source", "existing_score", "duplicate", "manifest"])
def test_report_rejects_invalid_or_duplicated_regrade_provenance(tmp_path, regraded, change):
    config, original, ledger_path, ledger = regraded
    paths = [ledger_path]
    if change in ("source", "existing_score"):
        row = json.loads(original.read_text())
        row["reward"] = 1
        original.write_text(json.dumps(row))
        if change == "existing_score":
            ledger["outcomes"][0]["source"]["outcome_sha256"] = hashlib.sha256(
                original.read_bytes()
            ).hexdigest()
            ledger_path.write_text(json.dumps(ledger))
    elif change == "duplicate":
        paths.append(ledger_path)
    else:
        Path(ledger["outcomes"][0]["source"]["manifest"]).write_text("{}")
    with pytest.raises(ValueError):
        reporter.make_report(tmp_path, config, ["first"], paths)
