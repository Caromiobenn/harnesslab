import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from harnesslab.models import RunRecord, RunStatus, UsageMetrics
from harnesslab.reporting import load_run_records, summarize_run_records, write_summary


def _run(run_id: str, harness: str, *, success: bool) -> RunRecord:
    now = datetime.now(UTC)
    return RunRecord(
        run_id=run_id,
        experiment=f"experiment-{harness}",
        task_id="task.v1@1",
        harness=harness,
        model="model-a",
        repeat=0,
        seed=42,
        status=RunStatus.COMPLETED,
        success=success,
        started_at=now,
        ended_at=now,
        metrics=UsageMetrics(
            model_calls=2,
            tool_calls=1,
            input_tokens=100,
            output_tokens=20,
            duration_ms=500,
        ),
    )


def test_summary_rebuilds_paired_harness_metrics(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    runs = [_run("a", "baseline", success=True), _run("b", "planning", success=False)]
    (artifact / "runs.jsonl").write_text(
        "".join(f"{run.model_dump_json()}\n" for run in runs), encoding="utf-8"
    )

    summary = summarize_run_records(load_run_records([tmp_path]))

    assert summary["run_count"] == 2
    assert summary["complete_pair_count"] == 1
    assert summary["harnesses"][0]["success_rate"] == 1.0
    assert summary["harnesses"][1]["validation_failures"] == 1


def test_loader_rejects_duplicate_runs_and_writer_is_immutable(tmp_path: Path) -> None:
    run = _run("same", "baseline", success=True)
    for name in ("a", "b"):
        artifact = tmp_path / name
        artifact.mkdir()
        (artifact / "runs.jsonl").write_text(f"{run.model_dump_json()}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate run_id"):
        load_run_records([tmp_path])

    output = tmp_path / "summary.json"
    write_summary(output, {"ok": True})
    assert json.loads(output.read_text(encoding="utf-8")) == {"ok": True}
    with pytest.raises(FileExistsError):
        write_summary(output, {"ok": False})
