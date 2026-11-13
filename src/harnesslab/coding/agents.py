"""Native mini baseline and Deep Agents baseline behind Harbor's BaseAgent interface."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import threading
from contextlib import suppress
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from time import monotonic

from harbor.agents.base import BaseAgent
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import message_to_dict

from harnesslab.coding.backend import HarborSandboxBackend
from harnesslab.coding.config import (
    CodingConfig,
    model_settings,
    project_root,
    sampling_options,
    save_json,
    thinking_body,
)


class ModelRoundLimitReached(RuntimeError):
    """The trial has consumed its shared model-generation budget."""


class ExecutionTrace(BaseCallbackHandler):
    """Record actual model usage, including calls made by the default subagent."""

    raise_error = True

    def __init__(self, folder: Path, stopped: threading.Event, max_model_calls: int = 0):
        self.path = folder / "events.jsonl"
        self.lock = threading.Lock()
        self.stopped = stopped
        self.input_tokens = self.output_tokens = self.cache_tokens = self.calls = 0
        self.models: set[str] = set()
        self.roles: dict[str, str] = {}
        self.role_usage = {
            role: {"model_calls": 0, "input_tokens": 0, "output_tokens": 0}
            for role in ("actor", "grader")
        }
        self.finish_reasons: dict[str, int] = {}
        self.max_model_calls = max_model_calls
        self.started_calls = 0
        self.budget_exhausted = False

    def emit(self, kind: str, data: object, **metadata) -> None:
        with self.lock, self.path.open("a") as stream:
            stream.write(
                json.dumps(
                    {
                        "event": kind,
                        "data": data,
                        "timestamp": datetime.now(UTC).isoformat(),
                        **metadata,
                    },
                    default=str,
                )
                + "\n"
            )

    def on_chat_model_start(self, serialized, messages, **kwargs):
        del serialized
        if self.stopped.is_set():
            raise RuntimeError("Agent execution has ended")
        role = (
            "grader"
            if (kwargs.get("metadata") or {}).get("rubric_grader_configured_model")
            else "actor"
        )
        with self.lock:
            if 0 < self.max_model_calls <= self.started_calls:
                self.budget_exhausted = True
                raise ModelRoundLimitReached("Model-generation round limit reached")
            self.started_calls += 1
            self.roles[str(kwargs.get("run_id"))] = role
        self.emit("model_request", [[message_to_dict(m) for m in batch] for batch in messages])

    def on_llm_end(self, response, **kwargs):
        with self.lock:
            role = self.roles.pop(str(kwargs.get("run_id")), "actor")
        for batch in response.generations:
            for generation in batch:
                message = generation.message
                usage = message.usage_metadata or {}
                with self.lock:
                    self.calls += 1
                    self.input_tokens += usage.get("input_tokens", 0)
                    self.output_tokens += usage.get("output_tokens", 0)
                    self.cache_tokens += (usage.get("input_token_details") or {}).get(
                        "cache_read", 0
                    )
                    self.models.add(str(message.response_metadata.get("model_name", "unknown")))
                    self.role_usage[role]["model_calls"] += 1
                    self.role_usage[role]["input_tokens"] += usage.get("input_tokens", 0)
                    self.role_usage[role]["output_tokens"] += usage.get("output_tokens", 0)
                    reason = str(message.response_metadata.get("finish_reason", "unknown"))
                    self.finish_reasons[reason] = self.finish_reasons.get(reason, 0) + 1
                self.emit("model_response", message_to_dict(message), role=role)

    def on_tool_end(self, output, **kwargs):
        self.emit("tool_result", {"run_id": str(kwargs.get("run_id")), "output": str(output)})

    def on_tool_start(self, serialized, input_str, **kwargs):
        self.emit(
            "tool_start",
            {
                "run_id": str(kwargs.get("run_id")),
                "name": serialized.get("name"),
                "input": input_str,
            },
        )

    def on_tool_error(self, error, **kwargs):
        self.emit(
            "tool_error", {"run_id": str(kwargs.get("run_id")), "error_type": type(error).__name__}
        )


async def finish_worker(worker, stopped: threading.Event, timeout: int):
    stopped.set()
    if not worker.done():
        with suppress(Exception, asyncio.CancelledError):
            await asyncio.wait_for(asyncio.shield(worker), timeout=timeout)


class DeepAgentsCodingAgent(BaseAgent):
    @staticmethod
    def name() -> str:
        return "harnesslab-deepagents"

    def version(self) -> str:
        return version("deepagents")

    def __init__(self, *args, experiment: dict, group: str = "deepagents_default", **kwargs):
        super().__init__(*args, **kwargs)
        self.experiment = CodingConfig.model_validate(experiment)
        self.group = group

    async def setup(self, environment) -> None:
        if hasattr(environment, "begin_actor"):
            await environment.begin_actor(self.experiment.network_mode, self.logs_dir)

    async def run(self, instruction, environment, context) -> None:
        from deepagents import create_deep_agent
        from langchain_deepseek import ChatDeepSeek

        from harnesslab.coding.review import build_review

        settings = model_settings(project_root())
        config = self.experiment
        stopped = threading.Event()
        trace = ExecutionTrace(self.logs_dir, stopped, config.max_model_calls)
        backend = HarborSandboxBackend(
            environment, asyncio.get_running_loop(), stopped, self.logs_dir, config.command_timeout
        )
        model = ChatDeepSeek(
            model=settings["model"],
            api_key=settings["api_key"],
            api_base=settings["base_url"],
            max_tokens=config.max_output_tokens,
            timeout=config.request_timeout,
            max_retries=0,
            extra_body=thinking_body(config, settings),
            reasoning_effort=config.reasoning_effort,
            **sampling_options(config),
            **(
                {
                    "profile": {
                        "max_input_tokens": config.context_window_tokens,
                        "max_output_tokens": config.max_output_tokens,
                    }
                }
                if config.context_window_tokens
                else {}
            ),
        )
        middleware, review_input, ledger = build_review(
            self.group,
            model,
            backend,
            self.logs_dir,
            trace,
            config.max_review_iterations,
            instruction,
        )
        agent = create_deep_agent(model=model, backend=backend, middleware=middleware)
        observation = None
        invoke_config = {"callbacks": [trace], "recursion_limit": 10000}
        if config.langsmith_tracing:
            from harnesslab.coding.observability import StudyTrace

            observation = StudyTrace(
                project_root(),
                self.logs_dir,
                environment.environment_name,
                self.group,
                config,
                settings["model"],
            )
            invoke_config.update(observation.config)
            invoke_config["callbacks"].append(observation.tracer)
        started = monotonic()
        worker = asyncio.create_task(
            asyncio.to_thread(
                agent.invoke,
                {"messages": [{"role": "user", "content": instruction}], **review_input},
                config=invoke_config,
            )
        )
        result = {}
        try:
            result = await asyncio.shield(worker)
        except ModelRoundLimitReached:
            trace.emit("budget_stop", {"max_model_calls": config.max_model_calls})
        finally:
            actor_elapsed = monotonic() - started
            stopped.set()
            if hasattr(environment, "stop_actor_processes"):
                await environment.stop_actor_processes()
            await finish_worker(
                worker, stopped, max(config.request_timeout, config.command_timeout) + 30
            )
            if hasattr(environment, "end_actor"):
                await environment.end_actor(self.logs_dir)
            context.n_input_tokens = trace.input_tokens
            context.n_output_tokens = trace.output_tokens
            context.n_cache_tokens = trace.cache_tokens
            context.metadata = {
                "group": self.group,
                "deepagents_version": self.version(),
                "model_calls": trace.calls,
                "started_model_calls": trace.started_calls,
                "budget_exhausted": trace.budget_exhausted,
                "response_models": sorted(trace.models),
                "elapsed_seconds": actor_elapsed,
                "configuration": config.model_dump(),
                "role_usage": trace.role_usage,
                "finish_reasons": trace.finish_reasons,
                "review_outcome": (
                    {"status": "model_round_limit_reached"}
                    if trace.budget_exhausted
                    else ledger.outcomes[-1]
                    if ledger and ledger.outcomes
                    else None
                ),
            }
            save_json(self.logs_dir / "summary.json", context.model_dump())
            save_json(
                self.logs_dir / "messages.json",
                [message_to_dict(m) for m in result.get("messages", [])],
            )
            if observation:
                await asyncio.to_thread(observation.finish)


class MiniCommandBridge:
    def __init__(self, environment, loop, stopped, timeout, logs_dir):
        self.backend = HarborSandboxBackend(environment, loop, stopped, logs_dir, timeout)

    def execute(self, action):
        from minisweagent.exceptions import InterruptAgentFlow

        command = action["command"]
        if command.strip() == "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT":
            raise InterruptAgentFlow(
                {
                    "role": "exit",
                    "content": "Submitted",
                    "extra": {"exit_status": "Submitted", "submission": "Final environment state"},
                }
            )
        response = self.backend.execute(command)
        return {"returncode": response.exit_code, "output": response.output, "exception_info": ""}

    def get_template_vars(self):
        return {"system": "Linux", "release": "", "version": "", "machine": "x86_64"}

    def serialize(self):
        return {"info": {"environment": {"type": "harbor-hongkong-bridge"}}}


class MiniCodingAgent(BaseAgent):
    @staticmethod
    def name() -> str:
        return "harnesslab-mini-swe-agent"

    def version(self) -> str:
        return version("mini-swe-agent")

    def __init__(self, *args, experiment: dict, wall_time_seconds: float, **kwargs):
        super().__init__(*args, **kwargs)
        self.experiment = CodingConfig.model_validate(experiment)
        self.wall_time_seconds = wall_time_seconds

    async def setup(self, environment) -> None:
        if hasattr(environment, "begin_actor"):
            await environment.begin_actor(self.experiment.network_mode, self.logs_dir)

    async def run(self, instruction, environment, context) -> None:
        import minisweagent
        import yaml
        from minisweagent.agents.default import DefaultAgent
        from minisweagent.models.litellm_model import LitellmModel

        settings = model_settings(project_root())
        config = self.experiment
        data = (Path(minisweagent.__file__).parent / "config/mini.yaml").read_bytes()
        native = yaml.safe_load(data)
        options = dict(native["agent"])
        options.pop("mode", None)
        options.update(
            step_limit=config.max_model_calls,
            cost_limit=0,
            wall_time_limit_seconds=self.wall_time_seconds,
            output_path=self.logs_dir / "mini-trajectory.json",
        )
        model_options = dict(native["model"])
        model_options.update(
            model_name="openai/" + settings["model"], cost_tracking="ignore_errors"
        )
        model_options["model_kwargs"] = {
            **model_options.get("model_kwargs", {}),
            "api_base": settings["base_url"],
            "timeout": config.request_timeout,
            "num_retries": 0,
            "max_tokens": config.max_output_tokens,
            "reasoning_effort": config.reasoning_effort,
            "extra_body": thinking_body(config, settings),
            **sampling_options(config),
        }
        stopped = threading.Event()
        os.environ["OPENAI_API_KEY"] = settings["api_key"]
        bridge = MiniCommandBridge(
            environment, asyncio.get_running_loop(), stopped, config.command_timeout, self.logs_dir
        )
        model = LitellmModel(**model_options)
        model.abort_exceptions = [*model.abort_exceptions, ImportError, TypeError]
        agent = DefaultAgent(model, bridge, **options)
        started = monotonic()
        worker = asyncio.create_task(asyncio.to_thread(agent.run, instruction))
        result = {}
        try:
            result = await asyncio.shield(worker)
        finally:
            actor_elapsed = monotonic() - started
            stopped.set()
            if hasattr(environment, "stop_actor_processes"):
                await environment.stop_actor_processes()
            await finish_worker(
                worker, stopped, max(config.request_timeout, config.command_timeout) + 30
            )
            if hasattr(environment, "end_actor"):
                await environment.end_actor(self.logs_dir)
            usage = {"prompt_tokens": 0, "completion_tokens": 0, "prompt_cache_hit_tokens": 0}
            for message in agent.messages:
                raw = message.get("extra", {}).get("response") or {}
                if isinstance(raw, dict):
                    for key in usage:
                        usage[key] += (raw.get("usage") or {}).get(key, 0) or 0
                    if "prompt_cache_hit_tokens" not in (raw.get("usage") or {}):
                        usage["prompt_cache_hit_tokens"] += (
                            (raw.get("usage") or {}).get("prompt_tokens_details") or {}
                        ).get("cached_tokens", 0) or 0
            context.n_input_tokens = usage["prompt_tokens"]
            context.n_output_tokens = usage["completion_tokens"]
            context.n_cache_tokens = usage["prompt_cache_hit_tokens"]
            context.metadata = {
                "group": "mini",
                "mini_swe_version": self.version(),
                "prompt_sha256": hashlib.sha256(data).hexdigest(),
                "model_calls": agent.n_calls,
                "exit_status": result.get("exit_status"),
                "configuration": config.model_dump(),
                "elapsed_seconds": actor_elapsed,
            }
            save_json(self.logs_dir / "summary.json", context.model_dump())
