"""Experiment orchestration shared by the CLI and tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from harnesslab.config import LoadedExperiment
from harnesslab.harnesses import HarnessRequest, build_harness
from harnesslab.models import (
    ExperimentSummary,
    RunRecord,
    RunStatus,
    TraceEventKind,
    UsageMetrics,
    utc_now,
)
from harnesslab.reproducibility import canonical_sha256, file_sha256, runtime_metadata
from harnesslab.storage import ArtifactStore
from harnesslab.tracing import TraceRecorder
from harnesslab.validators import evaluate_task


@dataclass(frozen=True, slots=True)
class ExperimentResult:
    summary: ExperimentSummary
    runs: tuple[RunRecord, ...]
    output_directory: Path


def _new_artifact_directory(root: Path, experiment_name: str) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    return root / f"{experiment_name}-{timestamp}-{uuid4().hex[:8]}"


def run_experiment(
    loaded: LoadedExperiment,
    *,
    output_root: Path | None = None,
) -> ExperimentResult:
    config = loaded.config
    root = (output_root or loaded.output_directory).resolve()
    artifact_directory = _new_artifact_directory(root, config.experiment.name)
    store = ArtifactStore(artifact_directory)
    store.write_json(
        "manifest.json",
        {
            "schema_version": config.schema_version,
            "config_path": str(loaded.config_path),
            "config_sha256": file_sha256(loaded.config_path),
            "lockfile_sha256": file_sha256(loaded.config_path.parent.parent / "uv.lock"),
            "experiment": config.experiment,
            "harness": config.harness,
            "tasks": [
                {
                    "id": task.id,
                    "public_sha256": canonical_sha256(task.agent_view()),
                    "private_evaluation_sha256": canonical_sha256(
                        {
                            "expected": task.expected,
                            "validators": [
                                validator.model_dump(mode="json") for validator in task.validators
                            ],
                        }
                    ),
                    "full_definition_sha256": canonical_sha256(task),
                }
                for task in loaded.tasks
            ],
            "randomness": {
                "requested_seed": config.experiment.seed,
                "effective": False,
                "reason": "offline scripted model is deterministic and has no RNG",
            },
            "runtime": runtime_metadata(),
        },
    )

    harness = build_harness(config.harness.kind, config.harness.model)
    experiment_started_at = utc_now()
    experiment_clock = perf_counter()
    runs: list[RunRecord] = []

    for repeat in range(config.experiment.repeats):
        for task in loaded.tasks:
            run_id = uuid4().hex
            run_started_at = utc_now()
            run_clock = perf_counter()
            trace = TraceRecorder(
                run_id,
                sink=lambda event: store.append_jsonl("events.jsonl", [event]),
            )
            trace.emit(
                TraceEventKind.RUN_STARTED,
                task.id,
                payload={"repeat": repeat, "seed": config.experiment.seed + repeat},
            )

            try:
                execution = harness.execute(
                    HarnessRequest(
                        task=task.agent_view(),
                        scripted_fixture=task.offline_fixture,
                        seed=config.experiment.seed + repeat,
                    ),
                    trace,
                )
                evaluation = evaluate_task(task, execution.output)
                trace.emit(
                    TraceEventKind.VALIDATION_COMPLETED,
                    "deterministic_validators",
                    payload=evaluation.model_dump(mode="json"),
                )
                status = RunStatus.COMPLETED
                output = execution.output
                metrics = execution.metrics.model_copy(
                    update={"duration_ms": (perf_counter() - run_clock) * 1000}
                )
                error = None
                success = evaluation.passed
                diagnostics = execution.diagnostics
                trace.emit(
                    TraceEventKind.RUN_COMPLETED,
                    task.id,
                    payload={"success": success},
                )
            except Exception as exc:
                evaluation = None
                status = RunStatus.ERROR
                output = None
                metrics = usage_from_trace(
                    trace,
                    duration_ms=(perf_counter() - run_clock) * 1000,
                )
                error = f"{type(exc).__name__}: {exc}"
                success = False
                diagnostics = {"oracle_fields_visible": False}
                trace.emit(
                    TraceEventKind.RUN_ERRORED,
                    task.id,
                    payload={"error": error},
                )

            record = RunRecord(
                run_id=run_id,
                experiment=config.experiment.name,
                task_id=task.id,
                harness=config.harness.kind,
                model=config.harness.model,
                repeat=repeat,
                seed=config.experiment.seed + repeat,
                status=status,
                success=success,
                started_at=run_started_at,
                ended_at=utc_now(),
                output=output,
                evaluation=evaluation,
                metrics=metrics,
                diagnostics=diagnostics,
                error=error,
            )
            runs.append(record)
            store.append_jsonl("runs.jsonl", [record])

    ended_at = utc_now()
    successful_runs = sum(run.success for run in runs)
    execution_errors = sum(run.status is RunStatus.ERROR for run in runs)
    validation_failures = len(runs) - successful_runs - execution_errors
    summary = ExperimentSummary(
        experiment=config.experiment.name,
        harness=config.harness.kind,
        model=config.harness.model,
        total_runs=len(runs),
        successful_runs=successful_runs,
        validation_failures=validation_failures,
        execution_errors=execution_errors,
        success_rate=successful_runs / len(runs),
        started_at=experiment_started_at,
        ended_at=ended_at,
        duration_ms=(perf_counter() - experiment_clock) * 1000,
        artifact_directory=str(artifact_directory),
    )
    store.write_json("summary.json", summary)
    return ExperimentResult(summary=summary, runs=tuple(runs), output_directory=artifact_directory)


def usage_from_trace(trace: TraceRecorder, *, duration_ms: float) -> UsageMetrics:
    model_calls = sum(event.kind is TraceEventKind.MODEL_CALLED for event in trace.events)
    declared_tool_calls = sum(
        len(event.payload.get("tool_calls", []))
        for event in trace.events
        if event.kind is TraceEventKind.MODEL_RETURNED
        and isinstance(event.payload.get("tool_calls"), list)
    )
    observed_tool_calls = sum(event.kind is TraceEventKind.TOOL_CALLED for event in trace.events)
    input_tokens = sum(
        int(event.payload.get("input_tokens", 0))
        for event in trace.events
        if event.kind is TraceEventKind.MODEL_RETURNED
    )
    output_tokens = sum(
        int(event.payload.get("output_tokens", 0))
        for event in trace.events
        if event.kind is TraceEventKind.MODEL_RETURNED
    )
    return UsageMetrics(
        model_calls=model_calls,
        tool_calls=max(declared_tool_calls, observed_tool_calls),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        duration_ms=duration_ms,
    )
