from pathlib import Path

import pytest
from pydantic import ValidationError

from harnesslab.config import load_benchmark_experiment, load_experiment
from harnesslab.models import TaskCategory, TaskDefinition

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_load_smoke_experiment_resolves_references() -> None:
    loaded = load_experiment(PROJECT_ROOT / "configs/smoke.yaml")

    assert loaded.config.experiment.name == "offline-smoke"
    assert loaded.output_directory == PROJECT_ROOT / "artifacts/runs"
    assert [task.id for task in loaded.tasks] == ["smoke.sum-numbers"]


def test_task_schema_rejects_fixture_input_mismatch() -> None:
    with pytest.raises(ValidationError, match="must equal task input"):
        TaskDefinition.model_validate(
            {
                "id": "test.mismatch",
                "category": TaskCategory.STRUCTURED_OUTPUT,
                "instruction": "Add numbers.",
                "input": {"numbers": [1, 2]},
                "offline_fixture": {
                    "tool": "sum_numbers",
                    "arguments": {"numbers": [9, 9]},
                },
                "expected": {"sum": 3},
                "validators": [{"kind": "exact_match"}],
            }
        )


def test_load_benchmark_experiment_resolves_catalog_and_model() -> None:
    loaded = load_benchmark_experiment(
        PROJECT_ROOT / "configs/benchmark-openai-compatible.example.yaml"
    )

    assert loaded.config.schema_version == "0.2"
    assert loaded.config.harness.model.provider == "openai_compatible"
    assert loaded.config.harness.model.api_key_env is None
    assert len(loaded.cases) == 3
    assert loaded.cases[0].public.task_ref == "structured.contacts-normalize.v1@1"
    assert loaded.output_directory == PROJECT_ROOT / "artifacts/benchmarks"
