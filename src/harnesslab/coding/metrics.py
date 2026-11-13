"""Comparable measurements from saved responses, actual executions, and Harbor results."""

import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from harnesslab.coding.config import save_json


def text_length(value):
    if isinstance(value, str):
        return len(value)
    if isinstance(value, list):
        return sum(text_length(part.get("text", "")) for part in value if isinstance(part, dict))
    return 0


def response_row(message, usage, role, native=False):
    calls = message.get("tool_calls") or []
    details = usage.get("completion_tokens_details" if native else "output_token_details") or {}
    input_details = usage.get("prompt_tokens_details" if native else "input_token_details") or {}
    reasoning = message.get("reasoning_content") or (message.get("additional_kwargs") or {}).get(
        "reasoning_content"
    )
    return {
        "role": role,
        "input_tokens": usage.get("prompt_tokens" if native else "input_tokens"),
        "output_tokens": usage.get("completion_tokens" if native else "output_tokens"),
        "reasoning_tokens": details.get("reasoning_tokens" if native else "reasoning"),
        "cached_input_tokens": usage.get(
            "prompt_cache_hit_tokens",
            input_details.get("cached_tokens" if native else "cache_read"),
        ),
        "visible_text_chars": text_length(message.get("content")),
        "reasoning_text_chars": text_length(reasoning) if reasoning is not None else None,
        "tool_names": [(c.get("function") or c).get("name", "unknown") for c in calls],
        "tool_argument_chars": sum(
            text_length((c.get("function") or {}).get("arguments"))
            if native
            else len(json.dumps(c.get("args", {}), ensure_ascii=False))
            for c in calls
        ),
    }


def responses(agent_dir):
    native = agent_dir / "mini-trajectory.json"
    if native.exists():
        for message in json.loads(native.read_text())["messages"]:
            raw = (message.get("extra") or {}).get("response") or {}
            if not isinstance(raw, dict) or not raw.get("choices"):
                continue
            yield response_row(raw["choices"][0]["message"], raw.get("usage") or {}, "actor", True)
        return
    events = agent_dir / "events.jsonl"
    if events.exists():
        with events.open() as stream:
            for line in stream:
                event = json.loads(line)
                if event["event"] == "model_response":
                    message = event["data"]["data"]
                    yield response_row(
                        message, message.get("usage_metadata") or {}, event.get("role", "unknown")
                    )


def phase_seconds(phase):
    start, end = phase.get("started_at"), phase.get("finished_at")
    if not start or not end:
        return None
    return (
        datetime.fromisoformat(end.replace("Z", "+00:00"))
        - datetime.fromisoformat(start.replace("Z", "+00:00"))
    ).total_seconds()


def trial_metrics(trial: Path, result: dict) -> dict:
    agent = trial / "agent"
    rows = list(responses(agent))
    usage_keys = (
        "input_tokens",
        "output_tokens",
        "reasoning_tokens",
        "cached_input_tokens",
        "visible_text_chars",
        "reasoning_text_chars",
        "tool_argument_chars",
    )
    totals = {
        key: sum(row[key] for row in rows if row[key] is not None)
        if any(row[key] is not None for row in rows)
        else None
        for key in usage_keys
    }
    observed = {key: sum(row[key] is not None for row in rows) for key in usage_keys}
    tools = Counter(name for row in rows for name in row["tool_names"])
    executions = []
    path = agent / "environment-events.jsonl"
    if path.exists():
        executions = [json.loads(line) for line in path.read_text().splitlines()]
    metadata = (result.get("agent_result") or {}).get("metadata") or {}
    review_path = agent / "review.json"
    review = json.loads(review_path.read_text()) if review_path.exists() else {}
    submission = agent / "submission/manifest.json"
    capture = agent / "capture-timing.json"
    report = {
        "schema_version": 1,
        "model_responses": len(rows),
        "reported_model_calls": metadata.get("model_calls"),
        "tokens_and_lengths": totals,
        "field_observed_responses": observed,
        "response_measurements": rows,
        "model_issued_tool_calls": sum(tools.values()),
        "tool_calls_by_name": dict(tools),
        "environment_commands": len(executions) if path.exists() else None,
        "environment_command_failures": sum(
            bool(x.get("error_type")) or x.get("exit_code") != 0 for x in executions
        )
        if path.exists()
        else None,
        "environment_command_seconds_sum": sum(x["duration_seconds"] for x in executions)
        if path.exists()
        else None,
        "agent_seconds": metadata.get("elapsed_seconds"),
        "submission_capture_seconds": (
            json.loads(capture.read_text())["seconds"] if capture.exists() else None
        ),
        "trial_seconds": phase_seconds(result),
        "phase_seconds": {
            key: phase_seconds(value)
            for key, value in result.items()
            if isinstance(value, dict) and "started_at" in value
        },
        "role_usage": metadata.get("role_usage"),
        "candidates": len(review.get("candidates", [])),
        "evidence_checks": len(
            [x for x in review.get("evidence", []) if x["kind"] == "verification"]
        ),
        "review_outcome": metadata.get("review_outcome"),
        "submission": json.loads(submission.read_text()) if submission.exists() else None,
        "definitions": {
            "input_tokens": "Cumulative across responses, including cached input.",
            "output_tokens": "Provider usage; includes reasoning where returned.",
            "lengths": "Unicode characters, not token estimates; missing reasoning stays null.",
            "commands": (
                "Actual backend executions, including filesystem helpers; "
                "distinct from model tool calls."
            ),
            "time": "Command durations may overlap; agent time excludes artifact capture.",
        },
    }
    save_json(agent / "metrics.json", report)
    return report
