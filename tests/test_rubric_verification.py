import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from harnesslab.benchmark import load_benchmark_catalog
from harnesslab.config import OpenAICompatibleModelSettings, VerificationSettings
from harnesslab.harnesses.base import HarnessRequest
from harnesslab.harnesses.online import OnlineExecutionError, OnlineFrameworkAgentHarness
from harnesslab.harnesses.verification import CandidateObserver, runtime_gate
from harnesslab.models import HarnessKind
from harnesslab.tracing import TraceRecorder
from harnesslab.validators import evaluate_benchmark_submission
from harnesslab.workspace import apply_reference_files, materialize_workspace

ROOT = Path(__file__).resolve().parents[1]


class ToolModel(GenericFakeChatModel):
    def bind_tools(self, tools: Sequence, *, tool_choice: str | None = None, **kwargs: Any):
        del tools, tool_choice, kwargs
        return self


def message(content: str = "", **kwargs) -> AIMessage:
    return AIMessage(
        content=content,
        usage_metadata={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
        **kwargs,
    )


def verdict(passed: bool, evidence: bool = False) -> AIMessage:
    names = ["output_contract", "task_semantics", "input_integrity"]
    if evidence:
        names.append("current_evidence")
    criteria = [{"name": name, "passed": True} for name in names]
    if not passed:
        criteria[0] = {"name": names[0], "passed": False, "gap": "Missing required contacts field."}
    return message(
        tool_calls=[
            {
                "name": "GraderResponse",
                "id": f"grade-{passed}",
                "type": "tool_call",
                "args": {
                    "result": "satisfied" if passed else "needs_revision",
                    "explanation": "All pass." if passed else "Repair the output contract.",
                    "criteria": criteria,
                },
            }
        ]
    )


def harness(actor: list, grader: list, **verification) -> OnlineFrameworkAgentHarness:
    return OnlineFrameworkAgentHarness(
        kind=HarnessKind.DEEPAGENTS_DEFAULT,
        settings=OpenAICompatibleModelSettings(
            name="fake", base_url="http://unused", api_key_env=None
        ),
        verification=VerificationSettings(mode="rubric", **verification),
        model_factory=lambda _: ToolModel(messages=iter(actor)),
        grader_model_factory=lambda _: ToolModel(messages=iter(grader)),
    )


def test_real_rubric_graph_repairs_candidate_and_separates_nested_usage() -> None:
    case = load_benchmark_catalog(ROOT / "benchmarks/catalog-v0.2.yaml").cases[0]
    good = json.dumps(case.evaluation.reference_submission)
    adapter = harness([message("{}"), message(good)], [verdict(False), verdict(True)])
    result = adapter.execute(HarnessRequest(task=case.public.agent_view()), TraceRecorder("repair"))
    assert result.output == case.evaluation.reference_submission
    assert [e["result"] for e in result.diagnostics["rubric_evaluations"]] == [
        "needs_revision",
        "satisfied",
    ]
    assert len(result.diagnostics["candidates"]) == 2
    assert result.diagnostics["runtime_accepted"] is True
    roles = result.diagnostics["role_usage"]
    assert roles["actor"]["model_calls"] == roles["grader"]["model_calls"] == 2
    assert roles["grader"]["input_tokens"] == 200
    assert result.metrics.model_calls == 4
    assert result.metrics.input_tokens == 400


def test_evidence_tools_actually_run_and_bind_to_each_candidate() -> None:
    case = load_benchmark_catalog(ROOT / "benchmarks/catalog-v0.2.yaml").cases[0]
    inspect = message(
        tool_calls=[{"name": "inspect_candidate", "id": "inspect", "args": {}, "type": "tool_call"}]
    )
    adapter = harness(
        [message("{}"), message(json.dumps(case.evaluation.reference_submission))],
        [inspect, verdict(False, True), inspect, verdict(True, True)],
        evidence_tools=True,
    )
    result = adapter.execute(
        HarnessRequest(task=case.public.agent_view()), TraceRecorder("evidence")
    )
    diagnostics = result.diagnostics
    assert [item["ok"] for item in diagnostics["public_evidence"]] == [False, True]
    assert [item["candidate_id"] for item in diagnostics["public_evidence"]] == [
        item["candidate_id"] for item in diagnostics["candidates"]
    ]
    assert diagnostics["role_usage"]["grader"]["model_calls"] == 4
    assert diagnostics["runtime_accepted"] is True


def test_budget_exhaustion_is_not_accepted() -> None:
    case = load_benchmark_catalog(ROOT / "benchmarks/catalog-v0.2.yaml").cases[0]
    adapter = harness([message("{}")], [verdict(False)], max_iterations=1)
    result = adapter.execute(HarnessRequest(task=case.public.agent_view()), TraceRecorder("cap"))
    assert result.diagnostics["rubric_evaluations"][-1]["result"] == "max_iterations_reached"
    assert result.diagnostics["runtime_accepted"] is False


def test_grader_exception_does_not_accept_candidate() -> None:
    case = load_benchmark_catalog(ROOT / "benchmarks/catalog-v0.2.yaml").cases[0]
    adapter = harness([message("{}")], [])
    result = adapter.execute(HarnessRequest(task=case.public.agent_view()), TraceRecorder("error"))
    assert result.output == {}
    assert result.diagnostics["rubric_evaluations"][-1]["result"] == "grader_error"
    assert result.diagnostics["runtime_accepted"] is False


def test_generic_retry_submits_last_candidate_without_oracle_selection() -> None:
    case = load_benchmark_catalog(ROOT / "benchmarks/catalog-v0.2.yaml").cases[0]
    adapter = OnlineFrameworkAgentHarness(
        kind=HarnessKind.DEEPAGENTS_DEFAULT,
        settings=OpenAICompatibleModelSettings(
            name="fake", base_url="http://unused", api_key_env=None
        ),
        verification=VerificationSettings(mode="retry", max_iterations=3),
        model_factory=lambda _: ToolModel(
            messages=iter(
                [
                    message('{"candidate": 1}'),
                    message('{"candidate": 2}'),
                    message('{"candidate": 3}'),
                ]
            )
        ),
    )
    result = adapter.execute(HarnessRequest(task=case.public.agent_view()), TraceRecorder("retry"))
    assert result.output == {"candidate": 3}
    assert len(result.diagnostics["candidates"]) == 3
    assert not result.diagnostics["rubric_evaluations"]


def test_combined_budget_is_enforced_across_actor_and_grader() -> None:
    case = load_benchmark_catalog(ROOT / "benchmarks/catalog-v0.2.yaml").cases[0]
    adapter = harness([message("{}"), message("{}")], [verdict(False)], total_model_call_limit=2)
    with pytest.raises(OnlineExecutionError, match="combined model-call budget") as caught:
        adapter.execute(HarnessRequest(task=case.public.agent_view()), TraceRecorder("budget"))
    assert len(caught.value.diagnostics["candidates"]) == 1


def test_public_checker_is_not_the_hidden_business_oracle(tmp_path: Path) -> None:
    case = load_benchmark_catalog(ROOT / "benchmarks/catalog-v0.2.yaml").cases[2]
    workspace = materialize_workspace(case, tmp_path / "workspace")
    apply_reference_files(workspace, case.evaluation.reference_submission)
    output = workspace / "output/summary.json"
    data = json.loads(output.read_text())
    data["regions"][0]["paid_orders"] += 1
    output.write_text(json.dumps(data))
    observer = CandidateObserver(
        HarnessRequest(task=case.public.agent_view(), workspace=workspace), TraceRecorder("public")
    )
    observer.after_agent({"messages": [AIMessage(content="done")]}, None)
    assert observer.inspect_candidate()["ok"] is True
    assert evaluate_benchmark_submission(case, "done", workspace=workspace).passed is False
    with pytest.raises(ValueError, match="unsafe"):
        observer.read_public_file("/../private/reference.json")
    assert all("write" not in tool.name for tool in observer.evidence_tools())


def test_gate_rejects_unverified_or_incomplete_grader_claims() -> None:
    request = HarnessRequest(
        task=load_benchmark_catalog(ROOT / "benchmarks/catalog-v0.2.yaml")
        .cases[0]
        .public.agent_view()
    )
    observer = CandidateObserver(request, TraceRecorder("gate"))
    observer.after_agent({"messages": [AIMessage(content="{}")]}, None)
    evaluation = {"result": "satisfied", "criteria": [{"name": "output_contract", "passed": True}]}
    assert runtime_gate([evaluation], observer, evidence_tools=False) is False


@pytest.mark.parametrize("split,count", [("dev", 6), ("holdout", 18)])
def test_generated_suite_has_separate_instances_and_valid_references(
    split, count, tmp_path
) -> None:
    from harnesslab.cli import _evaluate_reference

    catalog = load_benchmark_catalog(ROOT / f"benchmarks/rubric-v1/{split}.yaml")
    assert len(catalog.cases) == count
    assert all(_evaluate_reference(case).passed for case in catalog.cases)
