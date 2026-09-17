"""Rebuild comparison tables directly from immutable benchmark run artifacts."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from harnesslab.models import RunRecord, RunStatus


def load_run_records(paths: Iterable[Path]) -> tuple[RunRecord, ...]:
    """Load every unique runs.jsonl below files or directories."""
    run_files: set[Path] = set()
    for raw_path in paths:
        path = raw_path.expanduser().resolve()
        if path.is_file():
            run_files.add(path)
        elif path.is_dir():
            run_files.update(path.rglob("runs.jsonl"))
        else:
            raise FileNotFoundError(f"artifact path does not exist: {path}")

    records: list[RunRecord] = []
    seen_run_ids: set[str] = set()
    for run_file in sorted(run_files):
        with run_file.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    record = RunRecord.model_validate_json(line)
                except Exception as exc:
                    raise ValueError(f"invalid run at {run_file}:{line_number}: {exc}") from exc
                if record.run_id in seen_run_ids:
                    raise ValueError(f"duplicate run_id across artifacts: {record.run_id}")
                seen_run_ids.add(record.run_id)
                records.append(record)
    if not records:
        raise ValueError("no benchmark runs found")
    return tuple(records)


def summarize_run_records(records: Iterable[RunRecord]) -> dict[str, Any]:
    """Build harness and task-level descriptive results without hidden exclusions."""
    runs = tuple(records)
    grouped: dict[tuple[str, str], list[RunRecord]] = defaultdict(list)
    by_task: dict[tuple[str, str, str], list[RunRecord]] = defaultdict(list)
    pair_harnesses: dict[tuple[str, int, int, str], set[str]] = defaultdict(set)
    harnesses: set[str] = set()
    model_harnesses: dict[str, set[str]] = defaultdict(set)

    for run in runs:
        key = (run.harness, run.model)
        grouped[key].append(run)
        by_task[(run.harness, run.model, run.task_id)].append(run)
        pair_harnesses[(run.task_id, run.repeat, run.seed, run.model)].add(run.harness)
        harnesses.add(run.harness)
        model_harnesses[run.model].add(run.harness)

    return {
        "schema_version": "0.1",
        "run_count": len(runs),
        "harness_count": len(harnesses),
        "complete_pair_count": sum(
            observed == model_harnesses[pair_key[3]]
            for pair_key, observed in pair_harnesses.items()
        ),
        "expected_pair_count": len(pair_harnesses),
        "harnesses": [
            _aggregate(harness, model, group) for (harness, model), group in sorted(grouped.items())
        ],
        "tasks": [
            {
                "task_id": task_id,
                **_aggregate(harness, model, group),
            }
            for (harness, model, task_id), group in sorted(by_task.items())
        ],
    }


def write_summary(path: Path, summary: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def _aggregate(harness: str, model: str, runs: list[RunRecord]) -> dict[str, Any]:
    count = len(runs)
    successes = sum(run.success for run in runs)
    execution_errors = sum(run.status is RunStatus.ERROR for run in runs)
    return {
        "harness": harness,
        "model": model,
        "runs": count,
        "successes": successes,
        "success_rate": successes / count,
        "validation_failures": count - successes - execution_errors,
        "execution_errors": execution_errors,
        "mean_model_calls": sum(run.metrics.model_calls for run in runs) / count,
        "mean_tool_calls": sum(run.metrics.tool_calls for run in runs) / count,
        "mean_input_tokens": sum(run.metrics.input_tokens for run in runs) / count,
        "mean_output_tokens": sum(run.metrics.output_tokens for run in runs) / count,
        "mean_duration_ms": sum(run.metrics.duration_ms for run in runs) / count,
        "total_estimated_cost_usd": sum(run.metrics.estimated_cost_usd for run in runs),
    }
