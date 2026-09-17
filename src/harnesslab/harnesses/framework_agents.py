"""LangChain and Deep Agents adapters sharing one answer-free task boundary."""

from __future__ import annotations

import json
from time import perf_counter
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from langchain.agents import create_agent
from langchain.agents.middleware import TodoListMiddleware
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from harnesslab.harnesses.base import HarnessExecution, HarnessRequest
from harnesslab.harnesses.scripted_model import ScriptedToolModel, build_scripted_responses
from harnesslab.models import HarnessKind, TraceEventKind, UsageMetrics
from harnesslab.tools import MockToolRegistry
from harnesslab.tracing import TraceRecorder


class FrameworkAgentHarness:
    """Execute a scripted model through a real LangChain or Deep Agents graph."""

    def __init__(
        self,
        *,
        kind: HarnessKind,
        model_name: str,
        tools: MockToolRegistry | None = None,
    ) -> None:
        if kind not in {
            HarnessKind.LANGCHAIN_BASELINE,
            HarnessKind.LANGCHAIN_PLANNING,
            HarnessKind.DEEPAGENTS_DEFAULT,
        }:
            raise ValueError(f"unsupported framework harness kind: {kind}")
        self.kind = kind
        self.model_name = model_name
        self.tools = tools or MockToolRegistry()

    def execute(self, request: HarnessRequest, trace: TraceRecorder) -> HarnessExecution:
        fixture = request.scripted_fixture
        if fixture is None:
            raise ValueError(f"{self.kind} requires a scripted_fixture for offline execution")
        if not self.model_name.startswith("scripted-"):
            raise ValueError(
                f"offline framework harness requires a scripted-* model, got {self.model_name!r}"
            )

        started = perf_counter()
        preview_output = self.tools.invoke(fixture.tool, fixture.arguments)
        planning = self.kind is HarnessKind.LANGCHAIN_PLANNING
        model = ScriptedToolModel(
            messages=iter(
                build_scripted_responses(
                    fixture,
                    preview_output,
                    include_planning=planning,
                )
            ),
            trace=trace,
            label=self.model_name,
        )
        tool = self.tools.as_langchain_tool(fixture.tool, trace)
        trace.emit(
            TraceEventKind.HARNESS_CONFIGURED,
            self.kind,
            payload={
                "framework": "deepagents"
                if self.kind is HarnessKind.DEEPAGENTS_DEFAULT
                else "langchain",
                "planning": planning,
                "scripted": True,
            },
        )

        if self.kind is HarnessKind.DEEPAGENTS_DEFAULT:
            agent = create_deep_agent(
                model=model,
                tools=[tool],
                system_prompt="Complete the task using only the public task input.",
                backend=StateBackend(),
            )
        else:
            middleware = [TodoListMiddleware()] if planning else []
            agent = create_agent(
                model=model,
                tools=[tool],
                middleware=middleware,
                system_prompt="Complete the task using only the public task input.",
            )

        result = agent.invoke(
            {"messages": [{"role": "user", "content": request.task.render_user_prompt()}]}
        )
        messages = list(result["messages"])
        output = _parse_final_output(messages)
        tool_calls = sum(
            len(message.tool_calls) for message in messages if isinstance(message, AIMessage)
        )
        tool_messages = sum(isinstance(message, ToolMessage) for message in messages)
        diagnostics = {
            "execution_mode": "scripted_contract",
            "framework": "deepagents"
            if self.kind is HarnessKind.DEEPAGENTS_DEFAULT
            else "langchain",
            "planning": planning,
            "bound_tools": list(model.bound_tool_names),
            "message_count": len(messages),
            "tool_messages": tool_messages,
            "todos": result.get("todos", []),
            "oracle_fields_visible": False,
        }
        return HarnessExecution(
            output=output,
            metrics=UsageMetrics(
                model_calls=model.model_calls,
                tool_calls=tool_calls,
                duration_ms=(perf_counter() - started) * 1000,
            ),
            diagnostics=diagnostics,
        )


def _parse_final_output(messages: list[BaseMessage]) -> Any:
    if not messages:
        raise ValueError("agent returned no messages")
    content = messages[-1].content
    if not isinstance(content, str):
        return content
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return content
