"""Online LangChain/Deep Agents adapters for OpenAI-compatible model servers."""

from __future__ import annotations

import os
from collections.abc import Callable
from threading import Lock
from time import perf_counter
from typing import Any
from uuid import UUID

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend, StateBackend
from deepagents.middleware.filesystem import FilesystemPermission
from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, TodoListMiddleware
from langchain_core.callbacks import BaseCallbackHandler, UsageMetadataCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import LLMResult
from langchain_openai import ChatOpenAI

from harnesslab.config import OpenAICompatibleModelSettings
from harnesslab.harnesses.base import HarnessExecution, HarnessRequest
from harnesslab.harnesses.framework_agents import _parse_final_output
from harnesslab.models import HarnessKind, TraceEventKind, UsageMetrics
from harnesslab.reproducibility import canonical_sha256
from harnesslab.tracing import TraceRecorder
from harnesslab.workspace import WorkspaceToolRegistry

ModelFactory = Callable[[int], BaseChatModel]


class FrameworkTraceCallback(BaseCallbackHandler):
    """Record model/tool lifecycle events without persisting prompt or tool contents."""

    def __init__(self, trace: TraceRecorder, *, model_name: str) -> None:
        self.trace = trace
        self.model_name = model_name
        self.model_calls = 0
        self.tool_calls = 0
        self.observed_tools: list[str] = []
        self._active_tools: dict[UUID, tuple[float, str]] = {}
        self._lock = Lock()

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        del serialized, run_id, kwargs
        with self._lock:
            self.model_calls += 1
            call_index = self.model_calls
        self.trace.emit(
            TraceEventKind.MODEL_CALLED,
            self.model_name,
            payload={
                "call_index": call_index,
                "batch_size": len(messages),
                "message_count": sum(len(batch) for batch in messages),
                "content_recorded": False,
            },
        )

    def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        del run_id, kwargs
        tool_calls: list[dict[str, str | None]] = []
        generation_count = 0
        input_tokens = 0
        output_tokens = 0
        for batch in response.generations:
            for generation in batch:
                generation_count += 1
                message = getattr(generation, "message", None)
                if isinstance(message, AIMessage):
                    tool_calls.extend(
                        {"name": call.get("name", "unknown"), "id": call.get("id")}
                        for call in message.tool_calls
                    )
                    if message.usage_metadata:
                        input_tokens += int(message.usage_metadata.get("input_tokens", 0))
                        output_tokens += int(message.usage_metadata.get("output_tokens", 0))
        self.trace.emit(
            TraceEventKind.MODEL_RETURNED,
            self.model_name,
            payload={
                "generation_count": generation_count,
                "tool_calls": tool_calls,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "content_recorded": False,
            },
        )

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        del run_id, kwargs
        self.trace.emit(
            TraceEventKind.MODEL_ERRORED,
            self.model_name,
            payload={"error_type": type(error).__name__, "message": str(error)},
        )

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        del kwargs
        name = str(serialized.get("name") or "unknown_tool")
        with self._lock:
            self.tool_calls += 1
            self.observed_tools.append(name)
            self._active_tools[run_id] = (perf_counter(), name)
        self.trace.emit(
            TraceEventKind.TOOL_CALLED,
            name,
            payload={
                "input_sha256": canonical_sha256(input_str),
                "content_recorded": False,
            },
        )

    def on_tool_end(
        self,
        output: Any,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        del kwargs
        started_at, name = self._pop_tool_start(run_id)
        self.trace.emit(
            TraceEventKind.TOOL_RETURNED,
            name,
            payload={"output_sha256": _safe_hash(output), "content_recorded": False},
            duration_ms=(perf_counter() - started_at) * 1000 if started_at else None,
        )

    def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        del kwargs
        started_at, name = self._pop_tool_start(run_id)
        self.trace.emit(
            TraceEventKind.TOOL_ERRORED,
            name,
            payload={"error_type": type(error).__name__, "message": str(error)},
            duration_ms=(perf_counter() - started_at) * 1000 if started_at else None,
        )

    def _pop_tool_start(self, run_id: UUID) -> tuple[float | None, str]:
        with self._lock:
            active = self._active_tools.pop(run_id, None)
        if active is None:
            return None, "unknown_tool"
        return active


class OnlineFrameworkAgentHarness:
    """Run one public task against a real OpenAI-compatible chat model."""

    def __init__(
        self,
        *,
        kind: HarnessKind,
        settings: OpenAICompatibleModelSettings,
        model_factory: ModelFactory | None = None,
    ) -> None:
        if kind not in {
            HarnessKind.LANGCHAIN_BASELINE,
            HarnessKind.LANGCHAIN_PLANNING,
            HarnessKind.DEEPAGENTS_DEFAULT,
        }:
            raise ValueError(f"unsupported online harness kind: {kind}")
        self.kind = kind
        self.settings = settings
        self.model_name = settings.name
        self._model_factory = model_factory

    def execute(self, request: HarnessRequest, trace: TraceRecorder) -> HarnessExecution:
        started = perf_counter()
        model = self._build_model(request.seed, request.task.limits.get("wall_clock_seconds"))
        trace_callback = FrameworkTraceCallback(trace, model_name=self.model_name)
        usage_callback = UsageMetadataCallbackHandler()
        planning = self.kind is HarnessKind.LANGCHAIN_PLANNING
        actor_model_calls = request.task.limits.get("actor_model_calls", 12)
        middleware: list[Any] = [
            ModelCallLimitMiddleware(run_limit=actor_model_calls, exit_behavior="error")
        ]
        if planning:
            middleware.insert(0, TodoListMiddleware())

        workspace_tools: list[Any] = []
        workspace_registry = None
        if request.task.workspace == "fresh":
            if request.workspace is None:
                raise ValueError("fresh workspace task did not receive a materialized workspace")
            workspace_registry = WorkspaceToolRegistry(
                request.workspace,
                writable_paths=request.task.writable_paths,
                max_calls=request.task.limits.get("domain_tool_calls", 30),
            )
            if self.kind is not HarnessKind.DEEPAGENTS_DEFAULT:
                workspace_tools = workspace_registry.as_langchain_tools()

        trace.emit(
            TraceEventKind.HARNESS_CONFIGURED,
            self.kind,
            payload={
                "framework": "deepagents"
                if self.kind is HarnessKind.DEEPAGENTS_DEFAULT
                else "langchain",
                "provider": self.settings.provider,
                "planning": planning,
                "scripted": False,
                "actor_model_call_limit": actor_model_calls,
                "workspace": request.task.workspace,
                "domain_tools": [tool.name for tool in workspace_tools],
            },
        )

        system_prompt = (
            "Complete the task using only the public task request. Follow its output contract "
            "exactly. When JSON is requested, return exactly one JSON value with no Markdown "
            "fence or explanatory text."
        )
        if self.kind is HarnessKind.DEEPAGENTS_DEFAULT:
            backend = (
                FilesystemBackend(root_dir=request.workspace, virtual_mode=True)
                if request.workspace is not None
                else StateBackend()
            )
            agent = create_deep_agent(
                model=model,
                tools=[],
                system_prompt=system_prompt,
                middleware=middleware,
                backend=backend,
                permissions=_workspace_permissions(request.task.writable_paths)
                if request.workspace is not None
                else None,
            )
        else:
            agent = create_agent(
                model=model,
                tools=workspace_tools,
                middleware=middleware,
                system_prompt=system_prompt,
            )

        result = agent.invoke(
            {"messages": [{"role": "user", "content": request.task.render_user_prompt()}]},
            config={
                "callbacks": [trace_callback, usage_callback],
                "recursion_limit": max(25, actor_model_calls * 4 + 5),
            },
        )
        messages = list(result["messages"])
        output = _parse_final_output(messages)
        input_tokens, output_tokens = _aggregate_usage(usage_callback, messages)
        estimated_cost = self._estimate_cost(input_tokens, output_tokens)
        usage_metadata = {
            model_name: dict(values) for model_name, values in usage_callback.usage_metadata.items()
        }
        diagnostics = {
            "execution_mode": "online",
            "framework": "deepagents"
            if self.kind is HarnessKind.DEEPAGENTS_DEFAULT
            else "langchain",
            "provider": self.settings.provider,
            "base_url": self.settings.base_url,
            "planning": planning,
            "message_count": len(messages),
            "tool_messages": sum(isinstance(message, ToolMessage) for message in messages),
            "observed_tools": trace_callback.observed_tools,
            "domain_tool_calls": workspace_registry.call_count
            if workspace_registry is not None
            else 0,
            "todos": result.get("todos", []),
            "usage_metadata": usage_metadata,
            "cost_priced": self.settings.input_cost_per_million_usd is not None,
            "oracle_fields_visible": False,
        }
        return HarnessExecution(
            output=output,
            metrics=UsageMetrics(
                model_calls=trace_callback.model_calls,
                tool_calls=trace_callback.tool_calls,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_cost_usd=estimated_cost,
                duration_ms=(perf_counter() - started) * 1000,
            ),
            diagnostics=diagnostics,
        )

    def _build_model(self, seed: int, wall_clock_seconds: int | None) -> BaseChatModel:
        if self._model_factory is not None:
            return self._model_factory(seed)
        timeout = self.settings.request_timeout_seconds
        if wall_clock_seconds is not None:
            timeout = min(timeout, float(wall_clock_seconds))
        return ChatOpenAI(
            model=self.settings.name,
            base_url=self.settings.base_url,
            api_key=_resolve_api_key(self.settings.api_key_env),
            temperature=self.settings.temperature,
            max_completion_tokens=self.settings.max_completion_tokens,
            timeout=timeout,
            max_retries=self.settings.max_retries,
            seed=seed,
            stream_usage=True,
            use_responses_api=False,
        )

    def _estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        input_price = self.settings.input_cost_per_million_usd
        output_price = self.settings.output_cost_per_million_usd
        if input_price is None or output_price is None:
            return 0.0
        return (input_tokens * input_price + output_tokens * output_price) / 1_000_000


def _resolve_api_key(environment_variable: str | None) -> str:
    if environment_variable is None:
        return "not-required"
    value = os.environ.get(environment_variable)
    if not value:
        raise RuntimeError(
            f"required API key environment variable is unset: {environment_variable}"
        )
    return value


def _workspace_permissions(writable_paths: list[str]) -> list[FilesystemPermission]:
    permissions = [
        FilesystemPermission(
            operations=["write"],
            paths=[path.rstrip("/"), f"{path.rstrip('/')}/**"],
            mode="allow",
        )
        for path in writable_paths
    ]
    permissions.append(FilesystemPermission(operations=["write"], paths=["/**"], mode="deny"))
    return permissions


def _aggregate_usage(
    callback: UsageMetadataCallbackHandler,
    messages: list[BaseMessage],
) -> tuple[int, int]:
    input_tokens = sum(
        int(item.get("input_tokens", 0)) for item in callback.usage_metadata.values()
    )
    output_tokens = sum(
        int(item.get("output_tokens", 0)) for item in callback.usage_metadata.values()
    )
    if input_tokens or output_tokens:
        return input_tokens, output_tokens

    for message in messages:
        if isinstance(message, AIMessage) and message.usage_metadata:
            input_tokens += int(message.usage_metadata.get("input_tokens", 0))
            output_tokens += int(message.usage_metadata.get("output_tokens", 0))
    return input_tokens, output_tokens


def _safe_hash(value: Any) -> str:
    try:
        return canonical_sha256(value)
    except (TypeError, ValueError):
        return canonical_sha256(repr(value))
