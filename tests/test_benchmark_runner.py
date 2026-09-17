import json
from pathlib import Path

from harnesslab.benchmark_runner import run_benchmark_experiment
from harnesslab.config import load_benchmark_experiment
from harnesslab.harnesses import HarnessExecution, HarnessRequest
from harnesslab.models import TraceEventKind, UsageMetrics
from harnesslab.runner import ExperimentResult
from harnesslab.tracing import TraceRecorder
from harnesslab.workspace import apply_reference_files

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG = PROJECT_ROOT / "configs/benchmark-openai-compatible.example.yaml"


class ReferenceFixtureHarness:
    model_name = "test-reference-fixture"

    def __init__(self, outputs: dict[str, object]) -> None:
        self.outputs = outputs
        self.requests: list[HarnessRequest] = []

    def execute(self, request: HarnessRequest, trace: TraceRecorder) -> HarnessExecution:
        self.requests.append(request)
        trace.emit(TraceEventKind.MODEL_CALLED, self.model_name)
        output = self.outputs[request.task.id]
        if request.workspace is not None:
            apply_reference_files(request.workspace, output)
            output = {"completed": True}
        trace.emit(TraceEventKind.MODEL_RETURNED, self.model_name)
        return HarnessExecution(
            output=output,
            metrics=UsageMetrics(model_calls=1),
            diagnostics={"oracle_fields_visible": False, "execution_mode": "test_fixture"},
        )


def test_benchmark_runner_keeps_oracle_outside_harness_boundary(tmp_path: Path) -> None:
    loaded = load_benchmark_experiment(CONFIG)
    fixture = ReferenceFixtureHarness(
        {case.public.id: case.evaluation.reference_submission for case in loaded.cases}
    )

    result: ExperimentResult = run_benchmark_experiment(
        loaded,
        output_root=tmp_path,
        harness=fixture,
    )

    assert result.summary.total_runs == 3
    assert result.summary.successful_runs == 3
    assert result.summary.execution_errors == 0
    assert all(run.success for run in result.runs)
    assert {request.task.id for request in fixture.requests} == {
        "structured.contacts-normalize.v1",
        "structured.invoice-reconcile.v1",
        "file.sales-rollup.v1",
    }
    for request in fixture.requests:
        public_fields = type(request.task).model_fields
        assert "expected" not in public_fields
        assert "validators" not in public_fields

    manifest = json.loads((result.output_directory / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "0.2"
    assert manifest["catalog_sha256"]
    assert len(manifest["cases"]) == 3
    assert manifest["harness"]["model"]["api_key_env"] is None
