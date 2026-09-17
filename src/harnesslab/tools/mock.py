"""Small deterministic tools for exercising the runner without external services."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel

from harnesslab.models import TraceEventKind
from harnesslab.tracing import TraceRecorder


class SumNumbersArguments(BaseModel):
    numbers: list[int | float]


def sum_numbers(arguments: dict[str, Any]) -> dict[str, int | float]:
    values = arguments.get("numbers")
    if not isinstance(values, list) or not values:
        raise ValueError("sum_numbers expects a non-empty 'numbers' list")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in values):
        raise TypeError("sum_numbers accepts only int or float values")
    return {"sum": sum(values)}


class MockToolRegistry:
    """Explicit allow-list of deterministic tools available to the mock harness."""

    def __init__(self) -> None:
        self._tools: dict[str, Callable[[dict[str, Any]], Any]] = {
            "sum_numbers": sum_numbers,
        }

    def invoke(self, name: str, arguments: dict[str, Any]) -> Any:
        try:
            tool = self._tools[name]
        except KeyError as exc:
            raise ValueError(f"unknown mock tool: {name}") from exc
        return tool(arguments)

    def as_langchain_tool(self, name: str, trace: TraceRecorder) -> BaseTool:
        """Expose an allow-listed deterministic tool through LangChain."""
        if name != "sum_numbers":
            raise ValueError(f"unknown mock tool: {name}")

        def traced_sum_numbers(numbers: list[int | float]) -> dict[str, int | float]:
            arguments = {"numbers": numbers}
            trace.emit(TraceEventKind.TOOL_CALLED, name, payload={"arguments": arguments})
            try:
                output = self.invoke(name, arguments)
            except Exception as exc:
                trace.emit(
                    TraceEventKind.TOOL_ERRORED,
                    name,
                    payload={"error": f"{type(exc).__name__}: {exc}"},
                )
                raise
            trace.emit(TraceEventKind.TOOL_RETURNED, name, payload={"observation": output})
            return output

        return StructuredTool.from_function(
            func=traced_sum_numbers,
            name=name,
            description="Add a non-empty list of numeric values and return a JSON sum.",
            args_schema=SumNumbersArguments,
        )
