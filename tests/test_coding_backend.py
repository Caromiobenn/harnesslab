"""Exercise the real Deep Agents backend contract without a host shell or cloud calls."""

import asyncio
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("harbor")

from harnesslab.coding.backend import HarborSandboxBackend


class MemoryEnvironment:
    session_id = "isolated-trial"

    def __init__(self):
        self.files = {}
        self.commands = []

    async def exec(self, command, timeout_sec):
        self.commands.append((command, timeout_sec))
        return SimpleNamespace(stdout="sandbox result", stderr="", return_code=7)

    async def upload_file(self, source_path, target_path):
        self.files[target_path] = Path(source_path).read_bytes()

    async def download_file(self, source_path, target_path):
        Path(target_path).write_bytes(self.files[source_path])


def test_tools_use_sandbox_and_preserve_exit_status(tmp_path):
    async def scenario():
        environment = MemoryEnvironment()
        backend = HarborSandboxBackend(
            environment, asyncio.get_running_loop(), threading.Event(), tmp_path
        )
        response = await asyncio.to_thread(backend.execute, "pytest", timeout=5)
        assert response.exit_code == 7
        assert response.output == "sandbox result"
        assert environment.commands == [("pytest", 5)]
        event = json.loads((tmp_path / "environment-events.jsonl").read_text())
        assert event["command"] == "pytest" and event["exit_code"] == 7
        assert event["duration_seconds"] >= 0 and event["started_at"]
        uploaded = await asyncio.to_thread(backend.upload_files, [("/app/code.py", b"print(1)")])
        downloaded = await asyncio.to_thread(backend.download_files, ["/app/code.py"])
        assert uploaded[0].error is None
        assert downloaded[0].content == b"print(1)"
        assert list((tmp_path / "transfers").iterdir()) == []

    asyncio.run(scenario())


def test_cancelled_agent_cannot_start_another_command(tmp_path):
    async def scenario():
        environment = MemoryEnvironment()
        stopped = threading.Event()
        backend = HarborSandboxBackend(environment, asyncio.get_running_loop(), stopped, tmp_path)
        stopped.set()
        with pytest.raises(RuntimeError, match="execution has ended"):
            await asyncio.to_thread(backend.execute, "touch /app/after-deadline")
        assert environment.commands == []

    asyncio.run(scenario())


def test_real_deepagents_execute_tool_uses_the_bridge(tmp_path):
    from deepagents import create_deep_agent
    from langchain_core.messages import AIMessage

    from harnesslab.harnesses.scripted_model import ScriptedToolModel

    class Trace:
        def emit(self, *args, **kwargs):
            pass

    async def scenario():
        environment = MemoryEnvironment()
        backend = HarborSandboxBackend(
            environment, asyncio.get_running_loop(), threading.Event(), tmp_path
        )
        model = ScriptedToolModel(
            messages=iter(
                [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {"id": "sandbox-call", "name": "execute", "args": {"command": "pytest"}}
                        ],
                    ),
                    AIMessage(content="The command failed with exit status 7."),
                ]
            ),
            trace=Trace(),
            label="sandbox-contract",
        )
        agent = create_deep_agent(model=model, backend=backend)
        result = await asyncio.to_thread(
            agent.invoke, {"messages": [{"role": "user", "content": "Run the test."}]}
        )
        assert environment.commands == [("pytest", 120)]
        assert "exit status 7" in result["messages"][-1].content

    asyncio.run(scenario())
