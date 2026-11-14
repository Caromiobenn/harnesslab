"""Full runtime preserves task permissions and keeps offline services offline during grading."""

import asyncio
import hashlib
import importlib.util
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from harnesslab.coding.config import save_json


@pytest.fixture
def native(tmp_path, monkeypatch):
    calls = []
    files = {}

    async def write(path, data, **kwargs):
        files[path] = data

    async def read(path, **kwargs):
        return files[path]

    async def update_network(policy):
        calls.append(("network", policy))

    class Base:
        def __init__(self, **kwargs):
            self._root = tmp_path
            self.environment_name = "service"
            self._source_fingerprint = "fingerprint"
            self._image_runtime = {"user": "root"}
            self._runtime_env = {}
            self._template_name = "template"
            self.logger = None
            self._sandbox = SimpleNamespace(
                files=SimpleNamespace(write=write, read=read),
                update_network=update_network,
                commands=SimpleNamespace(),
            )

        async def exec(self, command, **kwargs):
            calls.append(("exec", command, kwargs))
            return SimpleNamespace(return_code=0, stderr="", stdout='[{"reachable":false}]')

        async def _apply_network_policy(self, policy):
            calls.append(("baseline_policy", policy))

    monkeypatch.setitem(
        sys.modules, "benchmark_next_environment", SimpleNamespace(BenchmarkAliyunEnvironment=Base)
    )
    monkeypatch.setitem(
        sys.modules,
        "benchmark_next_command",
        SimpleNamespace(oracle_handle=lambda handle, *args: handle),
    )
    path = Path(__file__).resolve().parents[1] / "src/harnesslab/coding/native_environment.py"
    spec = importlib.util.spec_from_file_location("test_native_runtime", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    save_json(
        tmp_path / "manifest.json",
        {
            "tasks": {
                "service": {
                    "runtime_profile": "native",
                    "source_fingerprint": "fingerprint",
                    "capture_paths": ["/app", "/etc/service"],
                    "archives": [],
                }
            }
        },
    )
    environment = module.NativeStudyEnvironment(prerequisites_manifest="manifest.json")
    return module, environment, calls, files


def test_image_identity_and_offline_network_survive_verifier_phase_switch(native):
    _, environment, calls, _ = native
    assert environment.actor_user == "root"

    async def scenario():
        await environment._apply_network_policy("initial-public")
        environment._study_network = "offline"
        await environment._apply_network_policy("verifier-requested-public")

    asyncio.run(scenario())
    assert calls == [
        ("baseline_policy", "initial-public"),
        ("network", {"allow_internet_access": False, "allow_out": []}),
    ]


@pytest.mark.parametrize("mode", ["offline", "public"])
def test_begin_actor_records_baseline_and_image_identity_before_opening_commands(
    native, tmp_path, mode, monkeypatch
):
    module, environment, calls, files = native

    async def python(code, timeout=120):
        if code == module.PROCESS_SNAPSHOT:
            return SimpleNamespace(stdout='[{"pid":1,"start_ticks":1}]')
        files[module.CONTROL + "/baseline.json"] = b'{"/app/input":{"kind":"file"}}'
        return SimpleNamespace(stdout="")

    environment.python_command = python

    async def probe(self, command, **kwargs):
        calls.append(("exec", command, kwargs))
        return SimpleNamespace(
            return_code=0, stderr="", stdout=json.dumps([{"reachable": mode == "public"}])
        )

    monkeypatch.setattr(module.BenchmarkAliyunEnvironment, "exec", probe)
    environment.entry["env"] = {"HF_HOME": "/public-hub"}
    environment.entry["offline_env"] = {"HF_HUB_OFFLINE": "1"}
    asyncio.run(environment.begin_actor(mode, tmp_path / "agent"))
    assert environment._actor_active
    assert environment._scope is not None
    assert json.loads((tmp_path / "agent/network.json").read_text())["actor_user"] == "root"
    assert json.loads((tmp_path / "agent/submission/baseline.json").read_text())["/app/input"]
    assert calls[0] == ("network", {"allow_internet_access": mode == "public", "allow_out": []})
    expected = {"HF_HUB_OFFLINE": "1"} if mode == "offline" else {}
    assert environment._runtime_env == expected
    assert json.loads((tmp_path / "agent/network.json").read_text())["offline_env"] == expected


def test_reference_control_runs_in_same_network_phase_and_ends_phase_after_failure(
    tmp_path, monkeypatch
):
    pytest.importorskip("harbor")
    from harnesslab.coding.controls import NativeOracleControl, OracleControl

    events = []

    async def begin(mode, logs):
        events.append(("begin", mode))

    async def end(logs):
        events.append(("end", str(logs)))

    async def fail(*args):
        events.append(("reference",))
        raise RuntimeError("reference failed")

    monkeypatch.setattr(OracleControl, "run", fail)
    agent = object.__new__(NativeOracleControl)
    agent.network_mode = "offline"
    agent.logs_dir = tmp_path
    environment = SimpleNamespace(begin_actor=begin, end_actor=end)

    async def scenario():
        await agent.setup(environment)
        with pytest.raises(RuntimeError, match="reference failed"):
            await agent.run("task", environment, None)

    asyncio.run(scenario())
    assert events == [("begin", "offline"), ("reference",), ("end", str(tmp_path))]


@pytest.mark.parametrize("corrupt", [False, True])
def test_submission_transfer_checks_hash_and_preserves_service_network(native, tmp_path, corrupt):
    module, environment, calls, files = native
    folder = tmp_path / "agent"
    (folder / "submission").mkdir(parents=True)
    environment._study_network = "offline"
    environment._baseline_processes = [{"pid": 1, "start_ticks": 1}]
    archive = b"captured archive bytes"
    manifest = {"sha256": hashlib.sha256(archive).hexdigest(), "parts": ["part-a", "part-b"]}
    files[module.CONTROL + "/submission.json"] = json.dumps(manifest)
    files["part-a"] = archive[:8]
    files["part-b"] = b"corrupted" if corrupt else archive[8:]

    async def python(code, timeout=120):
        return SimpleNamespace(
            stdout=json.dumps([{"pid": 1, "start_ticks": 1}, {"pid": 33, "start_ticks": 10}])
        )

    environment.python_command = python
    if corrupt:
        with pytest.raises(ValueError, match="checksum"):
            asyncio.run(environment.end_actor(folder))
        assert not (folder / "submission/manifest.json").exists()
    else:
        asyncio.run(environment.end_actor(folder))
        assert (folder / "submission/submission.tar.gz").read_bytes() == archive
        saved = json.loads((folder / "submission/manifest.json").read_text())
        assert saved["transfer_verified"] and saved["actor_user"] == "root"
        processes = json.loads((folder / "submission/processes.json").read_text())
        assert processes["new_at_submission"] == [{"pid": 33, "start_ticks": 10}]
    assert environment._study_network == "offline"
    assert not any(call[0] == "network" for call in calls)


def test_official_verifier_uses_cache_after_submission_once(native, tmp_path, monkeypatch):
    from harnesslab.coding import verifier_cache

    _, environment, calls, _ = native
    prepared = []
    environment.entry["verifier"] = {
        "archives": ["pinned-public-cache"],
        "env": {"UV_PYTHON": None},
    }
    environment._runtime_env["UV_PYTHON"] = "/actor/python"
    environment._logs = tmp_path
    environment._actor_active = True

    async def prepare(target, spec, control, python):
        prepared.append(spec)
        return {"UV_OFFLINE": "1", "PATH": "/cached-bin:/usr/bin"}

    monkeypatch.setattr(verifier_cache, "prepare_verifier", prepare)

    async def scenario():
        await environment.exec("ls /tests/test.sh")
        assert not prepared
        assert calls[-1][2]["env"]["UV_PYTHON"] == "/actor/python"
        environment._actor_active = False
        await environment.exec("bash /tests/test.sh", env={"TEST_VALUE": "preserved"})
        await environment.exec("bash /tests/test.sh")

    asyncio.run(scenario())
    assert prepared == [environment.entry["verifier"]]
    assert not environment._verifier_bootstrap
    assert calls[-2][2]["env"] == {
        "TEST_VALUE": "preserved",
        "UV_OFFLINE": "1",
        "PATH": "/cached-bin:/usr/bin",
    }
    assert json.loads((tmp_path / "verifier-prerequisites.json").read_text()) == prepared[0]


def test_prerequisites_added_after_sandbox_creation_reach_actor_commands(native):
    _, environment, calls, _ = native
    environment._actor_active = True
    environment._runtime_env.update(
        PIP_INDEX_URL="file:///cache/simple", APT_CONFIG="/cache/apt.conf"
    )
    asyncio.run(environment.exec("pip install build", env={"TEST_MARKER": "passed"}))
    assert calls[-1][2]["env"] == {
        "PIP_INDEX_URL": "file:///cache/simple",
        "APT_CONFIG": "/cache/apt.conf",
        "TEST_MARKER": "passed",
    }


@pytest.mark.skipif(os.name != "posix", reason="Actor commands run in a Linux shell")
@pytest.mark.parametrize("task_python", [False, True])
def test_actor_python_fallback_runs_helpers_and_preserves_task_interpreter(
    native, tmp_path, task_python
):
    module, _, _, _ = native
    fallback = tmp_path / "runtime with spaces"
    task = tmp_path / "task-bin"
    fallback.mkdir()
    task.mkdir()
    for directory, label in [(fallback, "controller"), *([(task, "task")] if task_python else [])]:
        executable = directory / "python3"
        executable.write_text("#!/bin/sh\nprintf '" + label + "\\n'\n")
        executable.chmod(0o755)
    command = module.actor_python_command("python3 -c 'helper code'", str(fallback))
    result = subprocess.run(
        ["/bin/bash", "-c", command],
        env={"PATH": str(task)},
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == ("task" if task_python else "controller")


@pytest.mark.parametrize("enabled", [False, True])
def test_actor_dispatch_preserves_already_prepared_commands_during_process_tracking(
    native, monkeypatch, enabled
):
    module, environment, _, _ = native
    environment.entry["actor_python_fallback"] = enabled
    environment._actor_active = True
    observed = {}

    async def dispatch_parent(self, command, **kwargs):
        observed["launched"] = command
        return SimpleNamespace(pid="sdk-command")

    def wrap(sandbox, command, python):
        observed.update(command=command, python=python)
        return "tracked-command", SimpleNamespace(record_path="identity-record")

    class Scope:
        async def dispatch(self, launch, cleanup):
            return await launch()

    monkeypatch.setattr(
        module.BenchmarkAliyunEnvironment, "_dispatch_command", dispatch_parent, raising=False
    )
    monkeypatch.setattr(module, "process_group_command", wrap)
    environment._scope = Scope()
    asyncio.run(
        environment._dispatch_command(
            "python3 helper.py", cwd="/app", env={}, timeout_sec=120, user="root"
        )
    )
    expected = "python3 helper.py"
    assert observed == {"command": expected, "python": module.PYTHON, "launched": "tracked-command"}
    assert environment._command_records == [
        {"sdk_command_id": "sdk-command", "identity_file": "identity-record"}
    ]


@pytest.mark.skipif(os.name != "posix", reason="Actor commands run in a Linux shell")
@pytest.mark.parametrize("task_python", [False, True])
@pytest.mark.parametrize("actor_active", [False, True])
def test_fallback_runs_after_parent_image_path_restoration(
    native, tmp_path, monkeypatch, task_python, actor_active
):
    module, environment, _, _ = native
    fallback = tmp_path / "fallback"
    task = tmp_path / "task-bin"
    fallback.mkdir()
    task.mkdir()
    for directory, label in [(fallback, "fallback"), *([(task, "task")] if task_python else [])]:
        executable = directory / "python3"
        executable.write_text("#!/bin/sh\nprintf '" + label + "\\n'\n")
        executable.chmod(0o755)

    async def parent_exec(self, command, **kwargs):
        # Match the vendor's image PATH restoration before command dispatch.
        command = "export PATH=" + shlex.quote(str(task)) + "; " + command
        result = subprocess.run(["/bin/bash", "-c", command], capture_output=True, text=True)
        return SimpleNamespace(return_code=result.returncode, stdout=result.stdout)

    monkeypatch.setattr(module.BenchmarkAliyunEnvironment, "exec", parent_exec)
    monkeypatch.setattr(module, "ACTOR_PYTHON_BIN", str(fallback))
    environment.entry["actor_python_fallback"] = True
    environment._actor_active = actor_active
    result = asyncio.run(environment.exec("python3 --version"))
    if task_python or actor_active:
        assert result.return_code == 0
        assert result.stdout.strip() == ("task" if task_python else "fallback")
    else:
        assert result.return_code == 127
