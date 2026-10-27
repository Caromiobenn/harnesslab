"""Execution loop for Benchmark v0.2 public/private task pairs."""

from __future__ import annotations

import signal
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import current_thread, main_thread
from time import perf_counter
from uuid import uuid4

from harnesslab.config import LoadedBenchmarkExperiment
from harnesslab.harnesses import AgentHarness, HarnessRequest, build_online_harness
from harnesslab.models import ExperimentSummary, RunRecord, RunStatus, TraceEventKind, utc_now
from harnesslab.reproducibility import canonical_sha256, file_sha256, runtime_metadata
from harnesslab.runner import ExperimentResult, usage_from_trace
from harnesslab.storage import ArtifactStore
from harnesslab.tracing import TraceRecorder
from harnesslab.validators import evaluate_benchmark_submission
from harnesslab.validators.snapshots import evaluate_candidate_snapshots
from harnesslab.workspace import materialize_workspace, snapshot_workspace


def run_benchmark_experiment(
    loaded: LoadedBenchmarkExperiment,
    *,
    output_root: Path | None = None,
    harness: AgentHarness | None = None,
    repeat_offset: int = 0,
) -> ExperimentResult:
    """Run selected v0.2 cases while keeping private evaluation outside the harness."""
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
            "catalog_path": str(loaded.catalog.catalog_path),
            "catalog_sha256": file_sha256(loaded.catalog.catalog_path),
            "lockfile_sha256": file_sha256(Path(__file__).resolve().parents[2] / "uv.lock"),
            "experiment": config.experiment,
            "repeat_offset": repeat_offset,
            "harness": config.harness,
            "cases": [
                {
                    "task_ref": case.public.task_ref,
                    "public_path": str(case.public_path),
                    "public_file_sha256": file_sha256(case.public_path),
                    "public_sha256": canonical_sha256(case.public),
                    "evaluation_path": str(case.evaluation_path),
                    "private_file_sha256": file_sha256(case.evaluation_path),
                    "private_evaluation_sha256": canonical_sha256(case.evaluation),
                    "workspace_fixture_path": str(case.workspace_fixture_path)
                    if case.workspace_fixture_path is not None
                    else None,
                    "workspace_fixture_sha256": file_sha256(case.workspace_fixture_path)
                    if case.workspace_fixture_path is not None
                    else None,
                }
                for case in loaded.cases
            ],
            "randomness": {
                "requested_seed": config.experiment.seed,
                "seed_forwarded_per_repeat": True,
                "temperature": config.harness.model.temperature,
                "determinism_guaranteed": False,
            },
            "runtime": runtime_metadata(),
        },
    )

    active_harness = harness or build_online_harness(
        config.harness.kind,
        config.harness.model,
        verification=config.harness.verification,
    )
    experiment_started_at = utc_now()
    experiment_clock = perf_counter()
    runs: list[RunRecord] = []

    for repeat in range(config.experiment.repeats):
        for case in loaded.cases:
            run_repeat = repeat + repeat_offset
            seed = config.experiment.seed + repeat
            run_id = uuid4().hex
            run_started_at = utc_now()
            run_clock = perf_counter()
            trace = TraceRecorder(
                run_id,
                sink=lambda event: store.append_jsonl("events.jsonl", [event]),
            )
            trace.emit(
                TraceEventKind.RUN_STARTED,
                case.public.task_ref,
                payload={"repeat": run_repeat, "seed": seed},
            )
            workspace = None
            initial_workspace = None

            try:
                workspace = materialize_workspace(
                    case,
                    artifact_directory / "workspaces" / run_id,
                )
                if workspace is not None:
                    initial_workspace = snapshot_workspace(workspace)
                with _wall_clock_limit(case.public.limits.wall_clock_seconds):
                    execution = active_harness.execute(
                        HarnessRequest(
                            task=case.public.agent_view(),
                            seed=seed,
                            workspace=workspace,
                        ),
                        trace,
                    )
                evaluation = evaluate_benchmark_submission(
                    case,
                    execution.output,
                    workspace=workspace,
                )
                trace.emit(
                    TraceEventKind.VALIDATION_COMPLETED,
                    "private_deterministic_validators",
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
                if workspace is not None:
                    diagnostics = {
                        **diagnostics,
                        "workspace": str(workspace),
                    }
                trace.emit(
                    TraceEventKind.RUN_COMPLETED,
                    case.public.task_ref,
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
                diagnostics = getattr(exc, "diagnostics", {"oracle_fields_visible": False})
                trace.emit(
                    TraceEventKind.RUN_ERRORED,
                    case.public.task_ref,
                    payload={"error": error},
                )

            if workspace is not None:
                store.write_json(
                    f"workspace-{run_id}.json",
                    {
                        "initial": initial_workspace,
                        "final": snapshot_workspace(workspace),
                    },
                )

            if diagnostics.get("candidates"):
                diagnostics["candidate_evaluations"] = evaluate_candidate_snapshots(
                    case, diagnostics["candidates"]
                )
            record = RunRecord(
                run_id=run_id,
                experiment=config.experiment.name,
                task_id=case.public.task_ref,
                harness=config.harness.kind,
                model=config.harness.model.name,
                repeat=run_repeat,
                seed=seed,
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
        model=config.harness.model.name,
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


def _new_artifact_directory(root: Path, experiment_name: str) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    return root / f"{experiment_name}-{timestamp}-{uuid4().hex[:8]}"


@contextmanager
def _wall_clock_limit(seconds: int) -> Iterator[None]:
    """Enforce a task deadline on Unix main-thread execution."""
    if not hasattr(signal, "SIGALRM") or current_thread() is not main_thread():
        yield
        return

    def raise_timeout(signum: int, frame: object) -> None:
        del signum, frame
        raise TimeoutError(f"task exceeded wall-clock limit of {seconds} seconds")

    started = perf_counter()
    previous_handler = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, raise_timeout)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, float(seconds))
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        previous_delay, previous_interval = previous_timer
        if previous_delay > 0:
            elapsed = perf_counter() - started
            signal.setitimer(
                signal.ITIMER_REAL,
                max(0.0, previous_delay - elapsed),
                previous_interval,
            )
