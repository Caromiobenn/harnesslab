"""Online LangChain/Deep Agents adapters for OpenAI-compatible model servers."""

from __future__ import annotations

import os
from collections.abc import Callable
from threading import Lock
from time import perf_counter
from typing import Any
from uuid import UUID

from deepagents import RubricMiddleware, create_deep_agent
from deepagents.backends import FilesystemBackend, StateBackend
from deepagents.middleware.filesystem import FilesystemPermission
from deepagents.middleware.rubric import GRADER_SYSTEM_PROMPT
from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, TodoListMiddleware
from langchain_core.callbacks import BaseCallbackHandler, UsageMetadataCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import LLMResult
from langchain_openai import ChatOpenAI

from harnesslab.config import OpenAICompatibleModelSettings, VerificationSettings
from harnesslab.harnesses.base import HarnessExecution, HarnessRequest
from harnesslab.harnesses.framework_agents import _parse_final_output
from harnesslab.harnesses.verification import (
    RUBRIC_VERSION,
    CandidateObserver,
    GenericRetryMiddleware,
    public_rubric,
    runtime_gate,
)
from harnesslab.models import HarnessKind, TraceEventKind, UsageMetrics
from harnesslab.reproducibility import canonical_sha256
from harnesslab.tracing import TraceRecorder
from harnesslab.workspace import WorkspaceToolRegistry

ModelFactory = Callable[[int], BaseChatModel]


class OnlineExecutionError(RuntimeError):
    """Preserve partial diagnostics when a bounded online execution fails."""

    def __init__(self, error: Exception, diagnostics: dict[str, Any]) -> None:
        super().__init__(f"{type(error).__name__}: {error}")
        self.diagnostics = diagnostics


class FrameworkTraceCallback(BaseCallbackHandler):
    """Record model/tool lifecycle events without persisting prompt or tool contents."""

    raise_error = True

    def __init__(
        self,
        trace: TraceRecorder,
        *,
        model_name: str,
        max_model_calls: int = 200,
        max_tool_calls: int = 500,
    ) -> None:
        self.trace = trace
        self.model_name = model_name
        self.model_calls = 0
        self.tool_calls = 0
        self.observed_tools: list[str] = []
        self._active_tools: dict[UUID, tuple[float, str]] = {}
        self._lock = Lock()
        self.max_model_calls = max_model_calls
        self.max_tool_calls = max_tool_calls
        self._model_roles: dict[UUID, str] = {}
        self.role_usage = {
            role: {"model_calls": 0, "input_tokens": 0, "output_tokens": 0}
            for role in ("actor", "grader")
        }

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        del serialized
        metadata = kwargs.get("metadata") or {}
        role = "grader" if "rubric_grader_configured_model" in metadata else "actor"
        with self._lock:
            if self.model_calls >= self.max_model_calls:
                raise RuntimeError(f"combined model-call budget exhausted: {self.max_model_calls}")
            self.model_calls += 1
            call_index = self.model_calls
            self._model_roles[run_id] = role
            self.role_usage[role]["model_calls"] += 1
        self.trace.emit(
            TraceEventKind.MODEL_CALLED,
            self.model_name,
            payload={
                "call_index": call_index,
                "role": role,
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
        del kwargs
        role = self._model_roles.get(run_id, "actor")
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
        with self._lock:
            self.role_usage[role]["input_tokens"] += input_tokens
            self.role_usage[role]["output_tokens"] += output_tokens
        self.trace.emit(
            TraceEventKind.MODEL_RETURNED,
            self.model_name,
            payload={
                "generation_count": generation_count,
                "role": role,
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
            if self.tool_calls >= self.max_tool_calls:
                raise RuntimeError(f"combined tool-call budget exhausted: {self.max_tool_calls}")
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
        verification: VerificationSettings | None = None,
        grader_model_factory: ModelFactory | None = None,
    ) -> None:
        if kind not in {
            HarnessKind.LANGCHAIN_BASELINE,
            HarnessKind.LANGCHAIN_PLANNING,
            HarnessKind.DEEPAGENTS_DEFAULT,
        }:
            raise ValueError(f"unsupported online harness kind: {kind}")
        self.kind = HarnessKind(kind)
        self.settings = settings
        self.model_name = settings.name
        self._model_factory = model_factory
        self.verification = verification or VerificationSettings()
        self._grader_model_factory = grader_model_factory

    def execute(self, request: HarnessRequest, trace: TraceRecorder) -> HarnessExecution:
        started = perf_counter()
        model = self._build_model(request.seed, request.task.limits.get("wall_clock_seconds"))
        trace_callback = FrameworkTraceCallback(
            trace,
            model_name=self.model_name,
            max_model_calls=self.verification.total_model_call_limit,
            max_tool_calls=self.verification.total_tool_call_limit,
        )
        usage_callback = UsageMetadataCallbackHandler()
        planning = self.kind is HarnessKind.LANGCHAIN_PLANNING
        actor_model_calls = request.task.limits.get("actor_model_calls", 12)
        middleware: list[Any] = [
            ModelCallLimitMiddleware(run_limit=actor_model_calls, exit_behavior="error")
        ]
        if planning:
            middleware.insert(0, TodoListMiddleware())
        observer = CandidateObserver(request, trace)
        evaluations: list[dict[str, Any]] = []

        def record_evaluation(evaluation: dict[str, Any]) -> None:
            evaluations.append(dict(evaluation))
            trace.emit(TraceEventKind.RUBRIC_EVALUATED, "runtime_grader", payload=dict(evaluation))

        if self.verification.mode == "retry":
            middleware.append(GenericRetryMiddleware(self.verification.max_iterations))
        elif self.verification.mode == "rubric":
            grader_settings = self.verification.grader_model or self.settings
            grader = (
                self._grader_model_factory(request.seed)
                if self._grader_model_factory is not None
                else self._build_chat_model(
                    grader_settings, request.seed, request.task.limits.get("wall_clock_seconds")
                )
            )
            middleware.append(
                RubricMiddleware(
                    model=grader,
                    system_prompt=GRADER_SYSTEM_PROMPT
                    + (
                        "\nStudy verdict policy: A missing file, invalid JSON, schema error, "
                        "wrong answer, or unmet task requirement is a CANDIDATE DEFECT. "
                        "Return needs_revision for candidate defects, with actionable gaps, "
                        "so the working agent can fix them. Do NOT return failed merely "
                        "because the candidate is wrong. failed is reserved for a rubric "
                        "that is itself malformed or impossible to interpret. "
                        "Use exactly the criterion names requested in the rubric."
                    ),
                    tools=observer.evidence_tools() if self.verification.evidence_tools else [],
                    max_iterations=self.verification.max_iterations,
                    grader_middleware=[
                        ModelCallLimitMiddleware(
                            run_limit=self.verification.grader_call_limit, exit_behavior="error"
                        )
                    ],
                    on_evaluation=record_evaluation,
                )
            )
        # after_agent hooks execute in reverse order: snapshot BEFORE grading/revision.
        # 在 Agent 自然停止时保存候选答案及工作区快照
        middleware.append(observer)

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
                "verification": self.verification.model_dump(mode="json"),
                "actor_model_call_limit": actor_model_calls,
                "workspace": request.task.workspace,
                "domain_tools": [tool.name for tool in workspace_tools],
            },
        )

        system_prompt = (
            "Complete the task using only the public task request. Follow its output contract "
            "exactly. When JSON is requested, return exactly one JSON value with no Markdown "
            "fence or explanatory text. Compute the ANSWER from Task input. "
            "The Required output contract describes the schema for your answer; "
            "it is NOT the answer. Never echo the schema or task metadata as your result."
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

        invocation: dict[str, Any] = {
            "messages": [{"role": "user", "content": request.task.render_user_prompt()}]
        }
        if self.verification.mode == "rubric":
            invocation["rubric"] = public_rubric(
                request, evidence_tools=self.verification.evidence_tools
            )
        failure = None
        try:
            result = agent.invoke(
                invocation,
                config={
                    "callbacks": [trace_callback, usage_callback],
                    "recursion_limit": max(100, actor_model_calls * 8 + 20),
                },
            )
        except Exception as exc:
            failure = exc
            result = {"messages": []}
        messages = list(result["messages"])
        output = _parse_final_output(messages) if messages else None
        input_tokens = sum(item["input_tokens"] for item in trace_callback.role_usage.values())
        output_tokens = sum(item["output_tokens"] for item in trace_callback.role_usage.values())
        if not input_tokens and not output_tokens:
            input_tokens, output_tokens = _aggregate_usage(usage_callback, messages)
        for role, counts in trace_callback.role_usage.items():
            prices = (
                (self.verification.grader_model or self.settings)
                if role == "grader"
                else self.settings
            )
            counts["estimated_cost_usd"] = (
                counts["input_tokens"] * (prices.input_cost_per_million_usd or 0)
                + counts["output_tokens"] * (prices.output_cost_per_million_usd or 0)
            ) / 1_000_000
        estimated_cost = sum(
            item["estimated_cost_usd"] for item in trace_callback.role_usage.values()
        )
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
            "verification_mode": self.verification.mode,
            "evidence_tools": self.verification.evidence_tools,
            "rubric_version": RUBRIC_VERSION if self.verification.mode == "rubric" else None,
            "rubric_sha256": canonical_sha256(invocation.get("rubric", "")),
            "rubric_evaluations": evaluations,
            "role_usage": trace_callback.role_usage,
            "candidates": observer.candidates,
            "public_evidence": observer.evidence,
            "runtime_accepted": runtime_gate(
                evaluations, observer, evidence_tools=self.verification.evidence_tools
            )
            if self.verification.mode == "rubric"
            else bool(messages),
        }
        if failure is not None:
            raise OnlineExecutionError(failure, diagnostics) from failure
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
        return self._build_chat_model(self.settings, seed, wall_clock_seconds)

    @staticmethod
    def _build_chat_model(
        settings: OpenAICompatibleModelSettings,
        seed: int,
        wall_clock_seconds: int | None,
    ) -> BaseChatModel:
        timeout = settings.request_timeout_seconds
        if wall_clock_seconds is not None:
            timeout = min(timeout, float(wall_clock_seconds))
        return ChatOpenAI(
            model=settings.name,
            base_url=settings.base_url,
            api_key=_resolve_api_key(settings.api_key_env),
            temperature=settings.temperature,
            max_completion_tokens=settings.max_completion_tokens,
            timeout=timeout,
            max_retries=settings.max_retries,
            seed=seed,
            stream_usage=True,
            use_responses_api=False,
            extra_body=settings.extra_body,
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
