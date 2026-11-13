"""Run both real agent loops against in-memory tools and deterministic model responses."""

import asyncio
import json
import threading
from types import SimpleNamespace

import pytest

pytest.importorskip("harbor")

from harbor.models.agent.context import AgentContext
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from harnesslab.coding.agents import DeepAgentsCodingAgent, MiniCodingAgent, finish_worker
from harnesslab.coding.config import CodingConfig


class Environment:
    session_id = "unit-test-only"

    def __init__(self):
        self.commands = []

    async def exec(self, command, timeout_sec):
        self.commands.append(command)
        return SimpleNamespace(stdout="OK", stderr="", return_code=0)


class ToolModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


@pytest.fixture
def profile(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(
        "DEEPSEEK_API_KEY=fixture-secret\nDEEPSEEK_MODEL=offline\n"
        "DEEPSEEK_BASE_URL=https://example.invalid\nDEEPSEEK_API_STYLE=aliyun\n"
    )
    monkeypatch.setenv("HARNESSLAB_ROOT", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "unused")
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    monkeypatch.setenv("MSWEA_CONFIGURED", "true")
    monkeypatch.setenv("MSWEA_SILENT_STARTUP", "1")
    monkeypatch.setenv("MSWEA_GLOBAL_CONFIG_DIR", str(tmp_path / "mini-config"))
    return CodingConfig(
        benchmark="terminal-bench-2.1",
        revision="fixture",
        tasks=["fixture"],
        purpose="offline integration contract",
    )


def test_deepagents_bridge_accounts_usage_and_keeps_secrets_out_of_trace(
    profile, tmp_path, monkeypatch
):
    responses = [
        AIMessage(
            content="",
            tool_calls=[{"id": "call", "name": "execute", "args": {"command": "echo OK"}}],
            usage_metadata={"input_tokens": 10, "output_tokens": 3, "total_tokens": 13},
        ),
        AIMessage(
            content="done",
            usage_metadata={"input_tokens": 12, "output_tokens": 4, "total_tokens": 16},
        ),
    ]
    captured = {}
    profile = profile.model_copy(
        update={"temperature": 1.0, "top_p": 0.95, "context_window_tokens": 1048576}
    )

    def create_model(**kwargs):
        captured.update(kwargs)
        return ToolModel(messages=iter(responses))

    monkeypatch.setattr("langchain_deepseek.ChatDeepSeek", create_model)
    environment = Environment()
    logs = tmp_path / "agent"
    logs.mkdir()
    agent = DeepAgentsCodingAgent(
        logs_dir=logs, model_name="offline", experiment=profile.model_dump()
    )
    context = AgentContext()
    asyncio.run(agent.setup(environment))
    asyncio.run(agent.run("Run echo OK", environment, context))
    assert environment.commands == ["echo OK"]
    assert context.n_input_tokens == 22
    assert context.n_output_tokens == 7
    assert context.metadata["model_calls"] == 2
    assert context.metadata["role_usage"]["actor"]["model_calls"] == 2
    assert captured["extra_body"] == {"enable_thinking": True}
    assert captured["temperature"] == 1.0 and captured["top_p"] == 0.95
    assert captured["profile"]["max_input_tokens"] == 1048576
    assert "fixture-secret" not in (logs / "events.jsonl").read_text()
    assert json.loads((logs / "messages.json").read_text())[-1]["data"]["content"] == "done"


def test_deadline_stops_tools_before_draining_a_pending_model_call(profile, tmp_path, monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    ordering = []

    def responses():
        entered.set()
        assert release.wait(5)
        ordering.append("model_returned")
        yield AIMessage(content="done")

    monkeypatch.setattr(
        "langchain_deepseek.ChatDeepSeek", lambda **kwargs: ToolModel(messages=responses())
    )

    class DeadlineEnvironment(Environment):
        async def stop_actor_processes(self):
            ordering.append("tools_stopped")
            release.set()

        async def end_actor(self, logs_dir):
            ordering.append("verifier_ready")

    logs = tmp_path / "agent"
    logs.mkdir()
    agent = DeepAgentsCodingAgent(
        logs_dir=logs, model_name="offline", experiment=profile.model_dump()
    )

    async def scenario():
        task = asyncio.create_task(
            agent.run("Finish the task", DeadlineEnvironment(), AgentContext())
        )
        assert await asyncio.to_thread(entered.wait, 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert ordering == ["tools_stopped", "model_returned", "verifier_ready"]


def test_mini_native_loop_executes_and_submits_without_serializing_api_key(
    profile, tmp_path, monkeypatch
):
    import litellm

    commands = iter(["echo OK", "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"])
    requests = []
    profile = profile.model_copy(update={"temperature": 1.0, "top_p": 0.95})

    def completion(**kwargs):
        requests.append(kwargs)
        return litellm.ModelResponse(
            model="offline",
            choices=[
                {
                    "index": 0,
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": f"command-{len(requests)}",
                                "type": "function",
                                "function": {
                                    "name": "bash",
                                    "arguments": json.dumps({"command": next(commands)}),
                                },
                            }
                        ],
                    },
                }
            ],
            usage={"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16},
        )

    monkeypatch.setattr(litellm, "completion", completion)
    logs = tmp_path / "agent"
    logs.mkdir()
    environment = Environment()
    agent = MiniCodingAgent(
        logs_dir=logs, model_name="offline", experiment=profile.model_dump(), wall_time_seconds=30
    )
    context = AgentContext()
    asyncio.run(agent.setup(environment))
    asyncio.run(agent.run("Run echo OK and submit", environment, context))
    assert environment.commands == ["echo OK"]
    assert len(requests) == 2
    assert context.n_input_tokens == 24
    assert context.metadata["exit_status"] == "Submitted"
    assert requests[0]["extra_body"] == {"enable_thinking": True}
    assert requests[0]["temperature"] == 1.0 and requests[0]["top_p"] == 0.95
    assert "fixture-secret" not in (logs / "mini-trajectory.json").read_text()


def test_finish_waits_for_inflight_work_after_setting_stop():
    async def scenario():
        stopped = threading.Event()

        async def worker():
            while not stopped.is_set():
                await asyncio.sleep(0)
            return "drained"

        task = asyncio.create_task(worker())
        await finish_worker(task, stopped, 1)
        assert task.result() == "drained"

    asyncio.run(scenario())


def test_transcript_review_is_invoked_and_grader_usage_is_separate(profile, tmp_path, monkeypatch):
    verdict = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "GraderResponse",
                "id": "grade",
                "args": {
                    "result": "satisfied",
                    "explanation": "Requirements supported by transcript.",
                    "criteria": [
                        {"name": name, "passed": True}
                        for name in ("deliverables", "behavior", "verification")
                    ],
                },
            }
        ],
        usage_metadata={"input_tokens": 30, "output_tokens": 5, "total_tokens": 35},
    )
    model = ToolModel(
        messages=iter(
            [
                AIMessage(
                    content="done",
                    usage_metadata={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
                ),
                verdict,
            ]
        )
    )
    monkeypatch.setattr("langchain_deepseek.ChatDeepSeek", lambda **kwargs: model)
    logs = tmp_path / "agent"
    logs.mkdir()
    agent = DeepAgentsCodingAgent(
        logs_dir=logs,
        model_name="offline",
        group="rubric_transcript",
        experiment=profile.model_dump(),
    )
    context = AgentContext()
    asyncio.run(agent.run("Implement code.py", Environment(), context))
    assert context.n_input_tokens == 40
    assert context.metadata["role_usage"]["grader"]["input_tokens"] == 30
    assert context.metadata["review_outcome"]["status"] == "satisfied"


def test_generation_limit_stops_real_deepagent_before_next_api_call(profile, tmp_path, monkeypatch):
    from itertools import count

    model = ToolModel(
        messages=(
            AIMessage(
                id=f"message-{i}",
                content="",
                tool_calls=[{"id": f"loop-{i}", "name": "execute", "args": {"command": "echo OK"}}],
            )
            for i in count()
        )
    )
    monkeypatch.setattr("langchain_deepseek.ChatDeepSeek", lambda **kwargs: model)
    logs = tmp_path / "agent"
    logs.mkdir()
    profile = profile.model_copy(update={"max_model_calls": 2})
    context = AgentContext()
    environment = Environment()
    agent = DeepAgentsCodingAgent(
        logs_dir=logs, model_name="offline", experiment=profile.model_dump()
    )
    asyncio.run(agent.run("Continue calling the tool", environment, context))
    assert context.metadata["started_model_calls"] == 2
    assert context.metadata["budget_exhausted"]
    assert len(environment.commands) == 2
