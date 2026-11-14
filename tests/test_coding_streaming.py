"""Exercise SSE reconstruction with the real SDK and native mini response parser."""

import asyncio
import json
import threading

import pytest

pytest.importorskip("harbor")

import httpx
from harbor.models.agent.context import AgentContext

from harnesslab.coding.agents import DeepAgentsCodingAgent, ExecutionTrace, MiniCodingAgent
from harnesslab.coding.config import CodingConfig
from harnesslab.coding.deepseek_adapter import MultimodalChatDeepSeek
from harnesslab.coding.streaming import collect_completion


def chunks(name="execute", command="echo OK", tool=True):
    base = {
        "id": "fixture-stream",
        "model": "fixture",
        "created": 1,
        "object": "chat.completion.chunk",
    }
    deltas = [
        {"role": "assistant", "reasoning_content": "Check "},
        {"reasoning_content": "the result."},
    ]
    if tool:
        arguments = json.dumps({"command": command})
        deltas += [
            {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "fixture-call",
                        "type": "function",
                        "function": {"name": name, "arguments": arguments[:10]},
                    }
                ]
            },
            {"tool_calls": [{"index": 0, "function": {"arguments": arguments[10:]}}]},
        ]
    else:
        deltas += [{"content": "done"}]
    for delta in deltas:
        yield {**base, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]}
    yield {
        **base,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls" if tool else "stop"}],
    }
    yield {
        **base,
        "choices": [],
        "usage": {
            "prompt_tokens": 12,
            "completion_tokens": 8,
            "total_tokens": 20,
            "prompt_tokens_details": {"cached_tokens": 4},
            "completion_tokens_details": {"reasoning_tokens": 5},
        },
    }


@pytest.fixture
def setup(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(
        "DEEPSEEK_API_KEY=fixture\nDEEPSEEK_MODEL=fixture\nDEEPSEEK_BASE_URL=https://example.invalid\nDEEPSEEK_API_STYLE=aliyun\n"
    )
    monkeypatch.setenv("HARNESSLAB_ROOT", str(tmp_path))
    monkeypatch.setenv("MSWEA_GLOBAL_CONFIG_DIR", str(tmp_path / "mini-config"))
    monkeypatch.setenv("MSWEA_CONFIGURED", "true")
    monkeypatch.setenv("MSWEA_SILENT_STARTUP", "1")
    monkeypatch.setenv("MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT", "1")
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    logs = tmp_path / "agent"
    logs.mkdir()
    config = CodingConfig(
        benchmark="terminal-bench-2.1",
        revision="fixture",
        tasks=["fixture"],
        purpose="stream contract",
        response_transport="streaming",
    )
    return logs, config


class Environment:
    session_id = "unit-test"

    def __init__(self):
        self.commands = []

    async def exec(self, command, timeout_sec):
        from types import SimpleNamespace

        self.commands.append(command)
        return SimpleNamespace(stdout="OK", stderr="", return_code=0)


def test_real_deepseek_sse_reassembles_tools_reasoning_and_usage(setup, monkeypatch):
    logs, config = setup
    requests = []

    def handle(request):
        payload = json.loads(request.content)
        requests.append(payload)
        data = chunks(tool=len(requests) == 1)
        body = "".join("data: " + json.dumps(chunk) + "\n\n" for chunk in data) + "data: [DONE]\n\n"
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=body)

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        monkeypatch.setattr(
            "harnesslab.coding.deepseek_adapter.MultimodalChatDeepSeek",
            lambda **kw: MultimodalChatDeepSeek(http_client=client, **kw),
        )
        environment = Environment()
        context = AgentContext()
        agent = DeepAgentsCodingAgent(
            logs_dir=logs, model_name="fixture", experiment=config.model_dump()
        )
        asyncio.run(agent.run("Run echo OK and finish", environment, context))
    assert environment.commands == ["echo OK"]
    assert all(r["stream"] and r["stream_options"] == {"include_usage": True} for r in requests)
    assert context.n_input_tokens == 24 and context.n_output_tokens == 16
    assert context.n_cache_tokens == 8 and context.metadata["model_calls"] == 2
    messages = json.loads((logs / "messages.json").read_text())
    assert messages[-1]["data"]["additional_kwargs"]["reasoning_content"] == "Check the result."
    assert messages[-1]["data"]["content"] == "done"


def test_native_mini_sse_reassembles_tools_reasoning_and_usage(setup, monkeypatch):
    import litellm

    logs, config = setup
    requests = []

    def completion(**kwargs):
        requests.append(kwargs)
        command = "echo OK" if len(requests) == 1 else "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
        return iter(litellm.ModelResponseStream(**row) for row in chunks("bash", command))

    monkeypatch.setattr(litellm, "completion", completion)
    environment = Environment()
    context = AgentContext()
    agent = MiniCodingAgent(
        logs_dir=logs, model_name="fixture", experiment=config.model_dump(), wall_time_seconds=30
    )
    asyncio.run(agent.run("Run echo OK and submit", environment, context))
    assert environment.commands == ["echo OK"]
    assert context.metadata["exit_status"] == "Submitted"
    assert all(r["stream"] and r["stream_options"] == {"include_usage": True} for r in requests)
    assert context.n_input_tokens == 24 and context.n_output_tokens == 16
    assert context.n_cache_tokens == 8
    saved = json.loads((logs / "mini-trajectory.json").read_text())
    responses = [
        m["extra"]["response"] for m in saved["messages"] if m.get("extra", {}).get("response")
    ]
    assert len(responses) == 2
    assert responses[-1]["choices"][0]["message"]["reasoning_content"] == "Check the result."


@pytest.mark.parametrize("cancelled", [False, True])
def test_interrupted_mini_stream_keeps_partial_data_without_a_response(setup, cancelled):
    import litellm

    logs, _ = setup
    stopped = threading.Event()
    closed = []

    def stream():
        try:
            if cancelled:
                stopped.set()
            yield litellm.ModelResponseStream(**next(chunks()))
            raise httpx.ReadError("fixture connection interruption")
        finally:
            closed.append(True)

    with pytest.raises(InterruptedError if cancelled else httpx.ReadError):
        collect_completion(stream(), [], stopped, logs)
    (partial,) = logs.glob("interrupted-stream-*.json")
    record = json.loads(partial.read_text())
    assert record["usage_complete"] is False and len(record["chunks"]) == 1
    assert closed == [True]


def test_deepagents_stream_stops_after_deadline_and_records_partial_error(setup):
    from langchain_core.messages import AIMessageChunk
    from langchain_core.outputs import ChatGenerationChunk, LLMResult

    logs, _ = setup
    stopped = threading.Event()
    trace = ExecutionTrace(logs, stopped)
    stopped.set()
    with pytest.raises(InterruptedError):
        trace.on_llm_new_token("late output")
    trace.on_llm_error(
        httpx.ReadError("fixture"),
        response=LLMResult(
            generations=[[ChatGenerationChunk(message=AIMessageChunk(content="partial"))]]
        ),
    )
    event = json.loads((logs / "events.jsonl").read_text())
    assert event["event"] == "model_error"
    assert event["data"]["partial_generations"][0][0]["data"]["content"] == "partial"
    assert trace.calls == 0
