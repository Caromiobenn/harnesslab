"""Explicit Deep Agents tracing and post-verifier metrics; credentials stay on the controller."""

import json
import time
from pathlib import Path
from uuid import uuid4

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


def publish_trial(root: Path, trial: Path, outcome: dict):
    path = trial / "agent/langsmith.json"
    if not path.exists():
        return None
    record = json.loads(path.read_text())
    metrics = outcome["metrics"]
    scores = {
        "official_reward": outcome["reward"],
        "pipeline_ok": int(outcome["pipeline_ok"]),
        "model_calls": metrics["model_responses"],
        "tool_calls": metrics["model_issued_tool_calls"],
        "environment_commands": metrics["environment_commands"],
        "command_failures": metrics["environment_command_failures"],
        "agent_seconds": metrics["agent_seconds"],
        "trial_seconds": metrics["trial_seconds"],
        "submission_capture_seconds": metrics["submission_capture_seconds"],
        "review_candidates": metrics["candidates"],
        "evidence_checks": metrics["evidence_checks"],
        **metrics["tokens_and_lengths"],
    }
    try:
        client, _ = tracing_client(root)
        for key, value in scores.items():
            if value is not None:
                client.create_feedback(
                    run_id=record["run_id"],
                    trace_id=record["run_id"],
                    key=key,
                    score=value,
                    comment="Measured by HarnessLab; official_reward comes from Harbor verifier.",
                )
        client.flush(timeout=30)
        record["feedback_status"] = "uploaded"
        record["feedback_keys"] = [k for k, v in scores.items() if v is not None]
    except Exception as exc:
        record.update(feedback_status="upload_error", feedback_error_type=type(exc).__name__)
    save_json(path, record)
    return record
