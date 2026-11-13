import json

from harnesslab.coding.config import save_json
from harnesslab.coding.metrics import trial_metrics


def test_deep_metrics_count_outputs_once_and_keep_missing_reasoning_unknown(tmp_path):
    agent = tmp_path / "agent"
    agent.mkdir()
    message = {
        "content": "你好",
        "tool_calls": [{"name": "execute", "args": {"command": "true"}}],
        "usage_metadata": {"input_tokens": 20, "output_tokens": 3},
    }
    events = [
        {"event": "model_request", "data": [message]},
        {"event": "model_response", "role": "grader", "data": {"data": message}},
    ]
    (agent / "events.jsonl").write_text("\n".join(json.dumps(x) for x in events))
    (agent / "environment-events.jsonl").write_text(
        json.dumps({"exit_code": 7, "duration_seconds": 2.5})
    )
    save_json(agent / "submission/manifest.json", {"sha256": "fixture"})
    save_json(agent / "capture-timing.json", {"seconds": 1.5})
    save_json(agent / "review.json", {"candidates": [{}], "evidence": [{"kind": "verification"}]})
    result = {
        "started_at": "2026-11-14T00:00:00Z",
        "finished_at": "2026-11-14T00:00:10Z",
        "agent_result": {"metadata": {"elapsed_seconds": 8, "model_calls": 1}},
    }
    report = trial_metrics(tmp_path, result)
    assert report["tokens_and_lengths"]["input_tokens"] == 20
    assert report["tokens_and_lengths"]["visible_text_chars"] == 2
    assert report["tokens_and_lengths"]["reasoning_tokens"] is None
    assert report["model_issued_tool_calls"] == 1
    assert report["environment_command_failures"] == 1
    assert report["environment_command_seconds_sum"] == 2.5
    assert report["trial_seconds"] == 10
    assert report["submission_capture_seconds"] == 1.5
    assert report["tokens_and_lengths"]["cached_input_tokens"] is None
    assert report["submission"]["sha256"] == "fixture"


def test_mini_metrics_use_native_usage_and_reasoning(tmp_path):
    agent = tmp_path / "agent"
    agent.mkdir()
    raw = {
        "choices": [
            {
                "message": {
                    "content": "",
                    "reasoning_content": "think",
                    "tool_calls": [{"function": {"name": "bash", "arguments": "{}"}}],
                }
            }
        ],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 9,
            "prompt_tokens_details": {"cached_tokens": 80},
            "completion_tokens_details": {"reasoning_tokens": 7},
        },
    }
    save_json(
        agent / "mini-trajectory.json",
        {"messages": [{"role": "user", "content": "task"}, {"extra": {"response": raw}}]},
    )
    report = trial_metrics(tmp_path, {})
    assert report["tokens_and_lengths"]["reasoning_tokens"] == 7
    assert report["tokens_and_lengths"]["cached_input_tokens"] == 80
    assert report["tokens_and_lengths"]["reasoning_text_chars"] == 5
    assert report["tokens_and_lengths"]["tool_argument_chars"] == 2
    assert report["tool_calls_by_name"] == {"bash": 1}
    assert report["environment_commands"] is None


def test_failed_trial_keeps_missing_usage_separate_from_zero(tmp_path):
    report = trial_metrics(tmp_path, {})
    assert report["model_responses"] == 0
    assert report["tokens_and_lengths"]["output_tokens"] is None
    assert report["agent_seconds"] is None
