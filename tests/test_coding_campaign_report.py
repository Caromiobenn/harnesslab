"""Campaign reports retain predecessor costs without double-counting shared batches."""

import importlib
import json
from pathlib import Path

import pytest

from harnesslab.coding.reuse import digest


@pytest.fixture
def reporter(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    return importlib.import_module("report_coding_campaign")


def study(root, name, prior=(), amendment=None):
    path = root / f"artifacts/expansions/{name}/study.json"
    path.parent.mkdir(parents=True)
    record = {
        "configuration": {"tasks": ["task"], "groups": ["mini"], "repeats": 1},
        "pilot_batches": [],
        "units": [{"batch": name}],
        "prior_studies": list(prior),
        "image_amendment": amendment,
    }
    path.write_text(json.dumps(record))
    return path, {"origin": str(path), "sha256": digest(path)}


def outcome(root, name, reward, tokens):
    path = root / f"artifacts/coding/{name}/task.outcome.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "task": "task",
                "group": "mini",
                "repeat": 0,
                "network_mode": "offline",
                "job_name": name,
                "pipeline_ok": reward is not None,
                "reward": reward,
                "cleanup_verified": True,
                "trial": None,
                "metrics": {"tokens_and_lengths": {"output_tokens": tokens}},
            }
        )
    )


def test_shared_predecessor_keeps_failed_cost_once(reporter, tmp_path):
    _old, ref = study(tmp_path / "old", "retired")
    outcome(tmp_path / "old", "retired", None, 7)
    _middle, middle_ref = study(tmp_path / "middle", "middle", [ref])
    latest, latest_ref = study(tmp_path / "latest", "latest", [ref, middle_ref], {"studies": [ref]})
    outcome(tmp_path / "latest", "latest", 1, 13)
    report = reporter.campaign_report(latest, latest_ref["sha256"])
    campaign = report["campaign"]
    assert campaign["ended_attempts"] == 2 and campaign["ended_cells"] == 1
    assert campaign["expected_cells"] == 2 and campaign["unscored_cells"] == 1
    assert len(campaign["studies"]) == 3 and len(campaign["outcome_sha256"]) == 2
    assert report["groups"][0]["all_ended_attempt_usage"]["output_tokens"]["sum"] == 20
    reporter.write_report(report, tmp_path / "report")
    assert (tmp_path / "report/trials.csv").read_text().count("task,") == 3
    assert (tmp_path / "report/groups.csv").exists()


def test_changed_predecessor_is_rejected(reporter, tmp_path):
    old, ref = study(tmp_path / "old", "old")
    latest, latest_ref = study(tmp_path / "latest", "latest", [ref])
    old.write_text(old.read_text() + " ")
    with pytest.raises(ValueError, match="Reused record changed"):
        reporter.campaign_inputs(latest, latest_ref["sha256"])


def test_two_official_scores_across_roots_are_rejected(reporter, tmp_path):
    _old, ref = study(tmp_path / "old", "old")
    latest, latest_ref = study(tmp_path / "latest", "latest", [ref])
    outcome(tmp_path / "old", "old", 0, 4)
    outcome(tmp_path / "latest", "latest", 1, 9)
    with pytest.raises(ValueError, match="Multiple official scores"):
        reporter.campaign_report(latest, latest_ref["sha256"])
