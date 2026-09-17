"""API-free harness used to test experiment infrastructure deterministically."""

from __future__ import annotations

from time import perf_counter

from harnesslab.harnesses.base import HarnessExecution, HarnessRequest
from harnesslab.models import TraceEventKind, UsageMetrics
from harnesslab.tools import MockToolRegistry
from harnesslab.tracing import TraceRecorder


class MockHarness:
    """Runs one declared fixture tool and relays its observation as the model output."""

    def __init__(self, *, model_name: str, tools: MockToolRegistry | None = None) -> None:
        self.model_name = model_name
        self.tools = tools or MockToolRegistry()

    def execute(self, request: HarnessRequest, trace: TraceRecorder) -> HarnessExecution:
        fixture = request.scripted_fixture
        if fixture is None:
            raise ValueError(f"mock harness requires scripted_fixture for task {request.task.id}")

        started = perf_counter()
        tool_started = perf_counter()
        trace.emit(
            TraceEventKind.TOOL_CALLED,
            fixture.tool,
            payload={"arguments": fixture.arguments},
        )
        observation = self.tools.invoke(fixture.tool, fixture.arguments)
        tool_duration = (perf_counter() - tool_started) * 1000
        trace.emit(
            TraceEventKind.TOOL_RETURNED,
            fixture.tool,
            payload={"observation": observation},
            duration_ms=tool_duration,
        )

        model_started = perf_counter()
        trace.emit(
            TraceEventKind.MODEL_CALLED,
            self.model_name,
            payload={"instruction": request.task.instruction},
        )
        output = observation
        model_duration = (perf_counter() - model_started) * 1000
        trace.emit(
            TraceEventKind.MODEL_RETURNED,
            self.model_name,
            payload={"output": output},
            duration_ms=model_duration,
        )

        return HarnessExecution(
            output=output,
            metrics=UsageMetrics(
                model_calls=1,
                tool_calls=1,
                duration_ms=(perf_counter() - started) * 1000,
            ),
            diagnostics={"execution_mode": "mock", "oracle_fields_visible": False},
        )
