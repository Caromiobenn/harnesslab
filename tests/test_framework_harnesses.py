from dataclasses import replace
from pathlib import Path

import pytest

from harnesslab.config import load_experiment
from harnesslab.models import HarnessKind
from harnesslab.runner import run_experiment

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("config_name", "kind", "model_calls", "tool_calls"),
    [
        ("offline-baseline.yaml", HarnessKind.LANGCHAIN_BASELINE, 2, 1),
        ("offline-planning.yaml", HarnessKind.LANGCHAIN_PLANNING, 4, 3),
        ("offline-deepagents.yaml", HarnessKind.DEEPAGENTS_DEFAULT, 2, 1),
    ],
)
def test_framework_harness_contracts(
    tmp_path: Path,
    config_name: str,
    kind: HarnessKind,
    model_calls: int,
    tool_calls: int,
) -> None:
    loaded = load_experiment(PROJECT_ROOT / "configs" / config_name)

    result = run_experiment(loaded, output_root=tmp_path)

    run = result.runs[0]
    assert run.harness == kind
    assert run.success is True
    assert run.metrics.model_calls == model_calls
    assert run.metrics.tool_calls == tool_calls
    assert run.diagnostics["oracle_fields_visible"] is False
    assert "sum_numbers" in run.diagnostics["bound_tools"]

    if kind is HarnessKind.LANGCHAIN_BASELINE:
        assert run.diagnostics["bound_tools"] == ["sum_numbers"]
    elif kind is HarnessKind.LANGCHAIN_PLANNING:
        assert "write_todos" in run.diagnostics["bound_tools"]
        assert run.diagnostics["todos"][0]["status"] == "completed"
    else:
        assert "task" in run.diagnostics["bound_tools"]
        assert "read_file" in run.diagnostics["bound_tools"]


def test_private_oracle_is_absent_from_agent_task_view(tmp_path: Path) -> None:
    loaded = load_experiment(PROJECT_ROOT / "configs/offline-baseline.yaml")
    secret = "PRIVATE_ORACLE_DO_NOT_EXPOSE"
    task = loaded.tasks[0].model_copy(update={"expected": secret})
    public_view = task.agent_view()
    public_fields = type(public_view).model_fields

    assert "expected" not in public_fields
    assert "validators" not in public_fields
    assert "offline_fixture" not in public_fields
    assert secret not in public_view.render_user_prompt()

    result = run_experiment(replace(loaded, tasks=(task,)), output_root=tmp_path)
    assert result.runs[0].success is False
    assert result.runs[0].status.value == "completed"
