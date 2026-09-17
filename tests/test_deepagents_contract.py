"""Pin the small part of the Deep Agents API that HarnessLab will build on."""

from collections.abc import Callable, Iterator, Sequence
from typing import Any

from deepagents import create_deep_agent
from langchain_core.language_models import LanguageModelInput
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from pydantic import Field


class ScriptedToolModel(GenericFakeChatModel):
    """Official fake-model pattern with tool binding enabled."""

    messages: Iterator[AIMessage | str] = Field(exclude=True)

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Callable[..., Any] | BaseTool],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Runnable[LanguageModelInput, AIMessage]:
        del tools, tool_choice, kwargs
        return self


def echo(text: str) -> str:
    """Return text unchanged."""
    return text


def test_deep_agent_executes_a_scripted_tool_call_without_an_api_key() -> None:
    model = ScriptedToolModel(
        messages=iter(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "echo",
                            "args": {"text": "ping"},
                            "id": "call_echo_1",
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(content="done"),
            ]
        )
    )
    agent = create_deep_agent(
        model=model,
        tools=[echo],
        system_prompt="Execute the requested tool call and report completion.",
    )

    result = agent.invoke({"messages": [{"role": "user", "content": "Call echo."}]})

    assert result["messages"][-1].content == "done"
    assert any(
        isinstance(message, ToolMessage) and message.content == "ping"
        for message in result["messages"]
    )
