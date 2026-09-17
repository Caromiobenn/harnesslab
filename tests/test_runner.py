import json
from dataclasses import replace
from pathlib import Path

from harnesslab.config import load_experiment
from harnesslab.models import OfflineFixture, RunStatus, TraceEventKind
from harnesslab.runner import run_experiment, usage_from_trace
from harnesslab.tracing import TraceRecorder

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_offline_experiment_writes_structured_artifacts(tmp_path: Path) -> None:
    loaded = load_experiment(PROJECT_ROOT / "configs/smoke.yaml")
    result = run_experiment(loaded, output_root=tmp_path)

    assert result.summary.total_runs == 1
    assert result.summary.successful_runs == 1
    assert result.summary.success_rate == 1.0
    assert result.runs[0].status is RunStatus.COMPLETED
    assert result.runs[0].output == {"sum": 42}

    assert {path.name for path in result.output_directory.iterdir()} == {
        "events.jsonl",
        "manifest.json",
        "runs.jsonl",
        "summary.json",
    }

    events = _read_jsonl(result.output_directory / "events.jsonl")
    event_kinds = [event["kind"] for event in events]
    assert event_kinds == [
        TraceEventKind.RUN_STARTED,
        TraceEventKind.TOOL_CALLED,
        TraceEventKind.TOOL_RETURNED,
        TraceEventKind.MODEL_CALLED,
        TraceEventKind.MODEL_RETURNED,
        TraceEventKind.VALIDATION_COMPLETED,
        TraceEventKind.RUN_COMPLETED,
    ]

    run_lines = _read_jsonl(result.output_directory / "runs.jsonl")
    assert len(run_lines) == 1
    assert run_lines[0]["success"] is True

    manifest = json.loads((result.output_directory / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["config_sha256"]
    assert manifest["lockfile_sha256"]
    assert manifest["tasks"][0]["public_sha256"]
    assert manifest["tasks"][0]["private_evaluation_sha256"]
    assert manifest["runtime"]["packages"]["deepagents"] == "0.7.14"
    assert manifest["randomness"]["effective"] is False


def test_validation_failure_is_data_not_an_execution_error(tmp_path: Path) -> None:
    loaded = load_experiment(PROJECT_ROOT / "configs/smoke.yaml")
    task = loaded.tasks[0].model_copy(update={"expected": {"sum": 999}})

    result = run_experiment(replace(loaded, tasks=(task,)), output_root=tmp_path)

    assert result.runs[0].status is RunStatus.COMPLETED
    assert result.runs[0].success is False
    assert result.summary.validation_failures == 1
    assert result.summary.execution_errors == 0


def test_tool_error_becomes_an_auditable_run_record(tmp_path: Path) -> None:
    loaded = load_experiment(PROJECT_ROOT / "configs/smoke.yaml")
    task = loaded.tasks[0].model_copy(
        update={
            "offline_fixture": OfflineFixture(
                tool="missing_tool",
                arguments=loaded.tasks[0].input,
            )
        }
    )

    result = run_experiment(replace(loaded, tasks=(task,)), output_root=tmp_path)

    run = result.runs[0]
    assert run.status is RunStatus.ERROR
    assert run.success is False
    assert run.evaluation is None
    assert run.error == "ValueError: unknown mock tool: missing_tool"
    assert run.metrics.tool_calls == 1
    assert result.summary.execution_errors == 1

    events = _read_jsonl(result.output_directory / "events.jsonl")
    assert events[-1]["kind"] == TraceEventKind.RUN_ERRORED


def test_usage_can_be_recovered_from_trace_after_later_error() -> None:
    trace = TraceRecorder("usage-recovery")
    trace.emit(TraceEventKind.MODEL_CALLED, "model")
    trace.emit(
        TraceEventKind.MODEL_RETURNED,
        "model",
        payload={
            "tool_calls": [{"name": "read_file", "id": "call-1"}],
            "input_tokens": 120,
            "output_tokens": 30,
        },
    )
    trace.emit(TraceEventKind.TOOL_CALLED, "read_file")
    trace.emit(TraceEventKind.TOOL_ERRORED, "read_file")

    usage = usage_from_trace(trace, duration_ms=250.0)

    assert usage.model_calls == 1
    assert usage.tool_calls == 1
    assert usage.input_tokens == 120
    assert usage.output_tokens == 30
    assert usage.duration_ms == 250.0
