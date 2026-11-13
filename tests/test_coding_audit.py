import json

from harnesslab.coding.audit import audit_batch, review_trial
from harnesslab.coding.config import save_json


def test_native_actions_keep_result_evidence_without_claiming_hacking(tmp_path):
    save_json(
        tmp_path / "mini-trajectory.json",
        {
            "messages": [
                {
                    "role": "assistant",
                    "extra": {
                        "actions": [{"command": "curl https://example.com", "tool_call_id": "a"}]
                    },
                },
                {"role": "tool", "tool_call_id": "a", "content": "downloaded"},
                {
                    "role": "assistant",
                    "extra": {
                        "actions": [
                            {
                                "command": "cat /sys/fs/cgroup/devices/devices.list",
                                "tool_call_id": "b",
                            }
                        ]
                    },
                },
            ]
        },
    )
    report = review_trial(tmp_path)
    assert report["action_count"] == 2
    assert report["flagged_actions"][0]["observed_result"]
    assert not report["flagged_actions"][1]["observed_result"]
    assert "Triage signals only" in report["interpretation"]


def test_deepagents_case_index_preserves_interventions_and_official_scores(tmp_path):
    trial = tmp_path / "trial"
    agent = trial / "agent"
    agent.mkdir(parents=True)
    events = [
        {"event": "tool_result", "data": {}},
        {
            "event": "model_response",
            "data": {
                "data": {
                    "tool_calls": [
                        {"name": "execute", "args": {"command": "cat /logs/verifier/reward.txt"}},
                        {"name": "execute", "args": {"command": "python code.py"}},
                    ]
                }
            },
        },
    ]
    (agent / "events.jsonl").write_text("\n".join(json.dumps(row) for row in events))
    folder = tmp_path / "artifacts/coding/fixture"
    save_json(
        folder / "model.outcome.json",
        {
            "job_name": "model",
            "task": "t",
            "group": "deepagents_default",
            "reward": 1,
            "pipeline_ok": True,
            "trial": str(trial),
        },
    )
    save_json(folder / "model.intervention.json", {"reason": "fixture intervention"})
    save_json(folder / "empty.outcome.json", {"group": "empty"})
    save_json(folder / "missing.outcome.json", {"group": "mini"})
    report = audit_batch(tmp_path, "fixture")
    assert len(report["trials"]) == 1
    row = report["trials"][0]
    assert row["reward"] == 1
    assert row["independent_verdict"] == "pending_case_review"
    assert row["intervention"]["reason"] == "fixture intervention"
    assert len(row["flagged_actions"]) == 1
    assert review_trial(tmp_path / "absent")["action_count"] == 0
