"""Continuation preserves original samples, even zeros, and rejects incompatible reuse."""

import copy
import json

import pytest

from harnesslab.coding.config import save_json
from harnesslab.coding.reuse import digest, load_reuse, save_reused


@pytest.fixture
def sample(tmp_path):
    plan = {
        "configuration": {
            "tasks": ["task"],
            "groups": ["mini"],
            "network_mode": "offline",
            "repeats": 1,
            "reasoning_effort": "high",
        },
        "model": "pinned",
        "base_url": "https://fixture.invalid",
        "api_style": "aliyun",
        "thinking_body": {},
        "tasks": [{"task": "task", "path": "/fixture/task", "agent_seconds": 900}],
        "source_hashes": {"actor.py": "unchanged", "shutdown.py": "old"},
    }
    target = copy.deepcopy(plan)
    target["source_hashes"]["shutdown.py"] = "fixed"
    row = {
        "task": "task",
        "group": "mini",
        "repeat": 0,
        "network_mode": "offline",
        "job_name": "original-job",
        "trial": "/fixture/original-trial",
        "reward": 0,
        "pipeline_ok": False,
        "cleanup_verified": True,
        "metrics": {"model_responses": 12},
    }
    source_path, outcome_path = tmp_path / "source.json", tmp_path / "original.outcome.json"
    save_json(source_path, plan)
    save_json(outcome_path, row)
    entry = {
        "outcome_path": str(outcome_path),
        "outcome_sha256": digest(outcome_path),
        "plan_path": str(source_path),
        "plan_sha256": digest(source_path),
        "compatible_groups": ["mini"],
        "compatibility_reason": "Actor unchanged; cleanup fix only.",
        "reviewed_source_differences": {"shutdown.py": {"before": "old", "after": "fixed"}},
    }
    manifest = {"target_source_hashes": target["source_hashes"], "references": [entry]}
    path = tmp_path / "reuse.json"
    save_json(path, manifest)
    return path, manifest, target, row


def test_zero_with_pipeline_error_is_kept_without_new_sample(sample, tmp_path):
    path, _, target, original = sample
    selected = load_reuse(path, target)[("offline", "task", "mini", 0)]
    reused = save_reused(tmp_path / "batch", "new", selected, False)
    assert all(reused[key] == value for key, value in original.items())
    assert reused["reuse"]["source_outcome"].endswith("original.outcome.json")
    assert save_reused(tmp_path / "batch", "new", selected, True) == reused
    with pytest.raises(ValueError, match="needs --resume"):
        save_reused(tmp_path / "batch", "new", selected, False)


@pytest.mark.parametrize(
    "change", ["source", "profile", "budget", "protocol", "group", "duplicate"]
)
def test_incompatible_reuse_is_rejected_before_launch(sample, change):
    path, manifest, target, _ = sample
    if change == "source":
        target["source_hashes"]["actor.py"] = "changed"
    elif change == "profile":
        target["model"] = "another-model"
    elif change == "budget":
        target["tasks"][0]["agent_seconds"] = 1800
    elif change == "protocol":
        target["configuration"]["reasoning_effort"] = "max"
    elif change == "group":
        manifest["references"][0]["compatible_groups"] = ["rubric_evidence"]
    else:
        manifest["references"].append(manifest["references"][0])
    save_json(path, manifest)
    with pytest.raises(ValueError):
        load_reuse(path, target)


def test_mutated_original_outcome_cannot_change_the_selected_result(sample):
    path, manifest, target, _ = sample
    from pathlib import Path

    original = Path(manifest["references"][0]["outcome_path"])
    data = json.loads(original.read_text())
    data["reward"] = 1
    save_json(original, data)
    with pytest.raises(ValueError, match="record changed"):
        load_reuse(path, target)
