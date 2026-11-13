"""Check actor identity, network gates, immutable prerequisites and phase cleanup."""

import asyncio
import hashlib
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from harnesslab.coding.config import save_json


@pytest.fixture
def environment(tmp_path, monkeypatch):
    calls = []
    stored = {"/app/run.py": b"async def run_tasks(tasks, max_concurrent): pass\n"}

    async def read(path, **kwargs):
        calls.append(("read", path, kwargs))
        return stored[path]

    async def write(path, data, **kwargs):
        calls.append(("write", path, kwargs))
        stored[path] = data

    async def exists(path):
        return path in stored

    async def network(policy):
        calls.append(("network", policy))

    class Base:
        def __init__(self, **kwargs):
            self._root = tmp_path
            self.environment_name = kwargs.get("environment_name", "cancel-async-tasks")
            self._source_fingerprint = "fixture"
            self._runtime_env = {}
            self._sandbox = SimpleNamespace(
                files=SimpleNamespace(read=read, write=write, exists=exists),
                update_network=network,
            )
            self.reachable = False
            self.return_code = 0

        async def start(self, force_build):
            calls.append(("start", force_build))

        async def exec(self, command, **kwargs):
            calls.append(("exec", command, kwargs))
            if command == "printf '%s' \"$PATH\"":
                return SimpleNamespace(
                    return_code=0, stdout="/image/bin:/usr/local/bin:/usr/bin", stderr=""
                )
            return SimpleNamespace(
                return_code=self.return_code,
                stderr="fixture error",
                stdout=(
                    "aGVsbG8="
                    if "base64.b64encode" in command
                    else json.dumps([{"reachable": self.reachable}])
                ),
            )

        async def upload_file(self, source, target):
            await write(target, Path(source).read_bytes())

        async def download_file(self, source, target):
            Path(target).write_bytes(await read(source))

        def _startup_env(self):
            return {}

    monkeypatch.setitem(
        sys.modules, "benchmark_next_environment", SimpleNamespace(BenchmarkAliyunEnvironment=Base)
    )
    path = Path(__file__).resolve().parents[1] / "src/harnesslab/coding/environment.py"
    spec = importlib.util.spec_from_file_location("harnesslab.coding.environment", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    archive = tmp_path / "prerequisites.tar.gz"
    archive.write_bytes(b"fixture")
    row = {
        "source_fingerprint": "fixture",
        "archive": archive.name,
        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
    }
    save_json(
        tmp_path / "manifest.json",
        {"tasks": {name: row for name in ("cancel-async-tasks", "compile-compcert")}},
    )
    return module, calls, archive


def test_network_gate_and_actor_file_tools_use_same_unprivileged_identity(environment, tmp_path):
    module, calls, _ = environment
    instance = module.StudyEnvironment(prerequisites_manifest="manifest.json")

    async def scenario():
        await instance.start(False)
        await instance.begin_actor("offline", tmp_path)
        await instance.exec("echo OK", user="root")
        source = tmp_path / "upload"
        source.write_bytes(b"hello")
        await instance.upload_file(source, "/app/new")
        await instance.download_file("/app/new", tmp_path / "download")
        await instance.end_actor(tmp_path)
        await instance.upload_file(source, "/app/root-phase")
        await instance.download_file("/app/root-phase", tmp_path / "root-download")

    asyncio.run(scenario())
    actor_command = next(row for row in calls if row[:2] == ("exec", "echo OK"))
    assert actor_command[2]["user"] == "harnesslab"
    file_commands = [row for row in calls if row[0] == "exec" and "base64." in row[1]]
    assert len(file_commands) == 3
    assert all(row[2]["user"] == "harnesslab" for row in file_commands)
    assert (tmp_path / "download").read_bytes() == b"hello"
    kill = next(
        i for i, row in enumerate(calls) if row[0] == "exec" and "controller-python -I -S" in row[1]
    )
    online = next(
        i for i, row in enumerate(calls) if row[0] == "network" and row[1]["allow_internet_access"]
    )
    assert kill < online
    assert json.loads((tmp_path / "network.json").read_text())["verified"]
    assert (tmp_path / "submission/run.py").exists()


def test_failed_egress_check_stops_before_actor_execution(environment, tmp_path):
    module, _, _ = environment
    instance = module.StudyEnvironment(prerequisites_manifest="manifest.json")
    instance.reachable = True
    with pytest.raises(RuntimeError, match="network policy"):
        asyncio.run(instance.begin_actor("offline", tmp_path))
    asyncio.run(instance.begin_actor("public", tmp_path))


def test_prerequisite_hash_and_preparation_errors_stop_start(environment):
    module, _, archive = environment
    instance = module.StudyEnvironment(prerequisites_manifest="manifest.json")
    archive.write_bytes(b"different")
    with pytest.raises(ValueError, match="archive changed"):
        asyncio.run(instance.start(False))
    archive.write_bytes(b"fixture")
    instance.return_code = 1
    with pytest.raises(RuntimeError, match="preparation failed"):
        asyncio.run(instance.start(False))


@pytest.mark.parametrize("network", ["offline", "public"])
def test_compcert_preserves_shell_path_and_sends_opam_environment_to_tools(
    environment, tmp_path, network
):
    module, calls, _ = environment
    instance = module.StudyEnvironment(
        prerequisites_manifest="manifest.json", environment_name="compile-compcert"
    )
    asyncio.run(instance.start(False))
    assert "OPAMROOT" not in instance._runtime_env
    instance.reachable = network == "public"
    asyncio.run(instance.begin_actor(network, tmp_path))
    asyncio.run(instance.exec("coqc --version"))
    expected = "/opt/harnesslab-prerequisites/opam/toolchain/bin:/image/bin:/usr/local/bin:/usr/bin"
    tool = next(row for row in calls if row[:2] == ("exec", "coqc --version"))
    assert tool[2]["env"]["PATH"] == expected
    assert tool[2]["env"]["OPAMROOT"] == "/opt/harnesslab-prerequisites/opam"
    assert tool[2]["env"]["OPAMSWITCH"] == "toolchain"
    assert tool[2]["user"] == "harnesslab"
    assert json.loads((tmp_path / "toolchain-environment.json").read_text())["PATH"] == expected


def test_shutdown_accepts_exited_children_waiting_for_parent_reaping(
    environment, tmp_path, monkeypatch
):
    module, _, _ = environment
    folders = []
    for pid, uid, state in [(101, 26000, "S"), (102, 26000, "Z"), (103, 0, "S")]:
        folder = tmp_path / str(pid)
        folder.mkdir()
        (folder / "status").write_text(f"Uid:\t{uid}\t{uid}\t{uid}\t{uid}\nState:\t{state}\n")
        folders.append(folder)
    monkeypatch.setattr(Path, "glob", lambda *args: folders)
    monkeypatch.setattr(time, "sleep", lambda _: None)
    killed = []

    def kill(pid, signal):
        killed.append(pid)
        path = tmp_path / str(pid) / "status"
        path.write_text(path.read_text().replace("State:\tS", "State:\tZ"))

    monkeypatch.setattr(os, "kill", kill)
    exec(module.STOP_ACTOR, {})
    assert killed == [101]
    assert "State:\tS" in (tmp_path / "103/status").read_text()


def test_shutdown_reports_a_process_that_remains_active(environment, tmp_path, monkeypatch):
    module, _, _ = environment
    folder = tmp_path / "101"
    folder.mkdir()
    (folder / "status").write_text("Uid:\t26000\t26000\t26000\t26000\nState:\tD\n")
    monkeypatch.setattr(Path, "glob", lambda *args: [folder])
    monkeypatch.setattr(time, "sleep", lambda _: None)
    monkeypatch.setattr(os, "kill", lambda *args: None)
    with pytest.raises(RuntimeError, match=r"Actor processes still active.*101"):
        exec(module.STOP_ACTOR, {})
