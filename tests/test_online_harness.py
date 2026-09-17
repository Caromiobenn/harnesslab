import json
from pathlib import Path

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from harnesslab.benchmark import load_benchmark_catalog
from harnesslab.config import OpenAICompatibleModelSettings
from harnesslab.harnesses.base import HarnessRequest
from harnesslab.harnesses.online import OnlineFrameworkAgentHarness
from harnesslab.models import HarnessKind, TraceEventKind
from harnesslab.tracing import TraceRecorder

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_online_harness_runs_real_agent_graph_with_injected_chat_model() -> None:
    case = load_benchmark_catalog(PROJECT_ROOT / "benchmarks/catalog-v0.2.yaml").cases[0]
    seeds: list[int] = []

    def model_factory(seed: int) -> GenericFakeChatModel:
        seeds.append(seed)
        return GenericFakeChatModel(
            messages=iter(
                [
                    AIMessage(
                        content=json.dumps(case.evaluation.reference_submission),
                        usage_metadata={
                            "input_tokens": 100,
                            "output_tokens": 40,
                            "total_tokens": 140,
                        },
                    )
                ]
            )
        )

    harness = OnlineFrameworkAgentHarness(
        kind=HarnessKind.LANGCHAIN_BASELINE,
        settings=OpenAICompatibleModelSettings(
            name="fake-openai-compatible",
            base_url="http://127.0.0.1:8000/v1",
            api_key_env=None,
            input_cost_per_million_usd=1.0,
            output_cost_per_million_usd=2.0,
        ),
        model_factory=model_factory,
    )
    trace = TraceRecorder("online-test")

    result = harness.execute(
        HarnessRequest(task=case.public.agent_view(), seed=17),
        trace,
    )

    assert seeds == [17]
    assert result.output == case.evaluation.reference_submission
    assert result.metrics.model_calls == 1
    assert result.metrics.input_tokens == 100
    assert result.metrics.output_tokens == 40
    assert result.metrics.estimated_cost_usd == 0.00018
    assert result.diagnostics["oracle_fields_visible"] is False
    assert [event.kind for event in trace.events] == [
        TraceEventKind.HARNESS_CONFIGURED,
        TraceEventKind.MODEL_CALLED,
        TraceEventKind.MODEL_RETURNED,
    ]
    returned = trace.events[-1]
    assert returned.payload["input_tokens"] == 100
    assert returned.payload["output_tokens"] == 40
