"""Deterministic chat model used for offline framework contract experiments."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Sequence
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import LanguageModelInput
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from pydantic import Field

from harnesslab.models import OfflineFixture, TraceEventKind


class ScriptedToolModel(GenericFakeChatModel):
    """A fake model that binds real tools and records each framework model turn."""

    messages: Iterator[AIMessage | str] = Field(exclude=True)
    trace: Any = Field(exclude=True)
    label: str = Field(exclude=True)
    bound_tool_names: tuple[str, ...] = Field(default=(), exclude=True)
    model_calls: int = Field(default=0, exclude=True)
    seen_message_text: list[str] = Field(default_factory=list, exclude=True)

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Callable[..., Any] | BaseTool],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Runnable[LanguageModelInput, AIMessage]:
        del tool_choice, kwargs
        self.bound_tool_names = tuple(_tool_name(tool) for tool in tools)
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.model_calls += 1
        self.seen_message_text.extend(str(message.content) for message in messages)
        self.trace.emit(
            TraceEventKind.MODEL_CALLED,
            self.label,
            payload={
                "call_index": self.model_calls,
                "message_count": len(messages),
                "bound_tools": list(self.bound_tool_names),
            },
        )
        result = super()._generate(
            messages,
            stop=stop,
            run_manager=run_manager,
            **kwargs,
        )
        message = result.generations[0].message
        tool_calls = message.tool_calls if isinstance(message, AIMessage) else []
        self.trace.emit(
            TraceEventKind.MODEL_RETURNED,
            self.label,
            payload={"content": message.content, "tool_calls": tool_calls},
        )
        return result


def _tool_name(tool: dict[str, Any] | type | Callable[..., Any] | BaseTool) -> str:
    if isinstance(tool, dict):
        function = tool.get("function")
        if isinstance(function, dict) and isinstance(function.get("name"), str):
            return function["name"]
        return str(tool.get("name", "provider_tool"))
    name = getattr(tool, "name", None) or getattr(tool, "__name__", None)
    return str(name or type(tool).__name__)


def build_scripted_responses(
    fixture: OfflineFixture,
    preview_output: Any,
    *,
    include_planning: bool,
) -> list[AIMessage]:
    """Create a tool-use script from fixture inputs, never from validator oracles."""
    task_label = f"Call {fixture.tool} with the supplied task input"
    responses: list[AIMessage] = []
    if include_planning:
        responses.append(
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "write_todos",
                        "args": {"todos": [{"content": task_label, "status": "in_progress"}]},
                        "id": "call_plan_start",
                        "type": "tool_call",
                    }
                ],
            )
        )

    responses.append(
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": fixture.tool,
                    "args": fixture.arguments,
                    "id": "call_task_tool",
                    "type": "tool_call",
                }
            ],
        )
    )

    if include_planning:
        responses.append(
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "write_todos",
                        "args": {"todos": [{"content": task_label, "status": "completed"}]},
                        "id": "call_plan_finish",
                        "type": "tool_call",
                    }
                ],
            )
        )

    responses.append(AIMessage(content=json.dumps(preview_output, ensure_ascii=False)))
    return responses
