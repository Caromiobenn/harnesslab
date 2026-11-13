"""Explicit Deep Agents tracing and post-verifier metrics; credentials stay on the controller."""

import json
import time
from pathlib import Path
from uuid import UUID, uuid4, uuid5

from dotenv import dotenv_values
from langchain_core.tracers.langchain import LangChainTracer, wait_for_all_tracers
from langsmith import Client
from langsmith.utils import LangSmithNotFoundError

from harnesslab.coding.config import save_json


def tracing_client(root: Path):
    settings = dotenv_values(root / ".env")
    key = settings.get("LANGSMITH_API_KEY")
    if not key:
        raise ValueError("LANGSMITH_API_KEY is required by this experiment")
    client = Client(
        api_key=key,
        api_url=settings.get("LANGSMITH_ENDPOINT") or None,
        workspace_id=settings.get("LANGSMITH_WORKSPACE_ID") or None,
        timeout_ms=15000,
    )
    return client, settings.get("LANGSMITH_PROJECT") or "harnesslab-tb21"


class StudyTrace:
    def __init__(self, root, folder, task, group, config, model):
        self.client, project = tracing_client(root)
        self.path = folder / "langsmith.json"
        self.run_id = uuid4()
        self.record = {"run_id": str(self.run_id), "project": project, "status": "started"}
        metadata = {
            "task_id": task,
            "group": group,
            "network_mode": config.network_mode,
            "reasoning_effort": config.reasoning_effort,
            "model_snapshot": model,
            "trial_id": folder.parent.name,
            "thread_id": str(self.run_id),
            "configuration": config.model_dump(),
        }
        self.tracer = LangChainTracer(client=self.client, project_name=project)
        self.config = {
            "run_id": self.run_id,
            "run_name": f"{task}/{group}/{config.network_mode}",
            "tags": ["terminal-bench-2.1", group, config.network_mode, config.reasoning_effort],
            "metadata": metadata,
        }
        save_json(self.path, self.record)

    def finish(self):
        try:
            wait_for_all_tracers()
            self.client.flush(timeout=20)
            for attempt in range(6):
                try:
                    run = self.client.read_run(self.run_id)
                    break
                except LangSmithNotFoundError:
                    if attempt == 5:
                        raise
                    time.sleep(2)
            self.record.update(
                status="uploaded",
                url=self.client.get_run_url(run=run, project_name=self.record["project"]),
            )
        except Exception as exc:
            self.record.update(status="upload_error", error_type=type(exc).__name__)
        save_json(self.path, self.record)


def measurements(outcome):
    metrics = outcome["metrics"]
    values = {
        "official_reward": outcome["reward"],
        "pipeline_ok": int(outcome["pipeline_ok"]),
        "model_calls": metrics["model_responses"],
        "tool_calls": metrics["model_issued_tool_calls"],
        "environment_commands": metrics["environment_commands"],
        "command_failures": metrics["environment_command_failures"],
        "agent_seconds": metrics["agent_seconds"],
        "agent_execution_phase_seconds": (metrics.get("phase_seconds") or {}).get(
            "agent_execution"
        ),
        "trial_seconds": metrics["trial_seconds"],
        "submission_capture_seconds": metrics["submission_capture_seconds"],
        "review_candidates": metrics["candidates"],
        "evidence_checks": metrics["evidence_checks"],
        **metrics["tokens_and_lengths"],
    }
    grader = (metrics.get("role_usage") or {}).get("grader") or {}
    values.update({"grader_" + key: value for key, value in grader.items()})
    result = {}
    for key, raw in values.items():
        if raw is None:
            continue
        scaled = key.endswith(("tokens", "chars"))
        unit = (
            "tokens"
            if key.endswith("tokens")
            else "characters"
            if key.endswith("chars")
            else "seconds"
            if key.endswith("seconds")
            else "count"
        )
        scale = 1_000_000 if scaled else 1
        result[key + "_millions" if scaled else key] = {
            "score": round(raw / scale, 4),
            "value": {"raw": raw, "unit": unit, "scale": scale},
        }
    return result


def persist_feedback(client, run, run_id, expected):
    existing = {item.key: item for item in client.list_feedback(run_ids=[run.id])}
    for key, item in expected.items():
        previous = existing.get(key)
        if previous and previous.value == item["value"]:
            continue
        if previous:
            client.update_feedback(previous.id, score=item["score"], value=item["value"])
        else:
            # Omit trace_id to make writes synchronous and surface API validation errors.
            client.create_feedback(
                run_id=run.id,
                session_id=run.session_id,
                start_time=run.start_time,
                key=key,
                score=item["score"],
                value=item["value"],
                feedback_id=uuid5(UUID(run_id), "harnesslab-metric-v2:" + key),
                comment="Canonical local measurement; value.raw preserves the exact value.",
            )
    for _attempt in range(6):
        observed = {item.key: item for item in client.list_feedback(run_ids=[run.id])}
        if all(
            key in observed and observed[key].value == item["value"]
            for key, item in expected.items()
        ):
            return True
        time.sleep(2)
    return False


def publish_trial(root: Path, trial: Path, outcome: dict):
    path = trial / "agent/langsmith.json"
    if not path.exists():
        return None
    record = json.loads(path.read_text())
    receipt_path = trial / "agent/langsmith-metrics.json"
    expected = measurements(outcome)
    if receipt_path.exists():
        previous = json.loads(receipt_path.read_text())
        if previous.get("verified") and previous.get("measurements") == expected:
            record.update(
                feedback_status="verified", feedback_keys=list(expected), url=previous["url"]
            )
            save_json(path, record)
            return record
    receipt = {
        "task": outcome.get("task"),
        "group": outcome.get("group"),
        "network": outcome.get("network_mode"),
        "run_id": record["run_id"],
        "measurements": expected,
        "verified": False,
    }
    try:
        client, project = tracing_client(root)
        run = client.read_run(record["run_id"])
        record["url"] = record.get("url") or client.get_run_url(run=run, project_name=project)
        receipt["url"] = record["url"]
        receipt["verified"] = persist_feedback(client, run, record["run_id"], expected)
        record["feedback_status"] = "verified" if receipt["verified"] else "verification_pending"
        record["feedback_keys"] = list(expected)
        record.pop("feedback_error_type", None)
    except Exception as exc:
        record.update(feedback_status="upload_error", feedback_error_type=type(exc).__name__)
        receipt["error_type"] = type(exc).__name__
    save_json(receipt_path, receipt)
    save_json(path, record)
    return record
