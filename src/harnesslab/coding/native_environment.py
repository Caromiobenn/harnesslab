"""Full-task runtime: image permissions, retained services and artifact deltas."""

from __future__ import annotations

import hashlib
import json
import shlex
from pathlib import Path
from time import monotonic

from benchmark_next_command import oracle_handle
from benchmark_next_environment import BenchmarkAliyunEnvironment

from harnesslab.coding.command_scope import ActorCommandScope, process_group_command
from harnesslab.coding.config import save_json
from harnesslab.coding.environment import NETWORK_PROBE

CONTROL = "/opt/harnesslab-controller"
PYTHON = CONTROL + "/python313/bin/python3.13"
PART_SIZE = 16 * 1024 * 1024

PROCESS_SNAPSHOT = """import json,os
from pathlib import Path
result=[]
for folder in Path('/proc').glob('[0-9]*'):
    if int(folder.name)==os.getpid(): continue
    try:
        fields=(folder/'stat').read_text().rsplit(')',1)[1].split()
        if fields[0] in ('Z','X'): continue
        result.append({'pid':int(folder.name),'ppid':int(fields[1]),'pgid':int(fields[2]),
            'start_ticks':int(fields[19]),'state':fields[0],
            'command':(folder/'cmdline').read_bytes().replace(b'\\0',b' ').decode(errors='replace'),
            'cwd':os.readlink(folder/'cwd')})
    except (FileNotFoundError,ProcessLookupError,PermissionError): pass
print(json.dumps(result))
"""


class NativeStudyEnvironment(BenchmarkAliyunEnvironment):
    def __init__(self, *args, prerequisites_manifest: str, **kwargs):
        super().__init__(*args, **kwargs)
        self.entry = json.loads((self._root / prerequisites_manifest).read_text())["tasks"][
            self.environment_name
        ]
        if self.entry["source_fingerprint"] != self._source_fingerprint:
            raise ValueError("Full-task prerequisites refer to a different environment")
        if self.entry["runtime_profile"] != "native":
            raise ValueError("Native runtime requires an explicit task profile")
        if not self.entry["capture_paths"]:
            raise ValueError("Declare the task's submission paths")
        self.actor_user = self._image_runtime["user"]
        self._actor_active = False
        self._study_network = None
        self._scope = None
        self._command_records = []
        self._baseline_processes = []
        self._logs = None
        self._study_verifier_env = None

    async def root_command(self, command, timeout=120):
        result = await super().exec(command, user="root", timeout_sec=timeout)
        if result.return_code:
            raise RuntimeError("Task runtime helper failed: " + (result.stderr or "")[-1200:])
        return result

    async def python_command(self, code, timeout=120):
        return await self.root_command(PYTHON + " -I -S -c " + shlex.quote(code), timeout)

    async def upload_archive(self, path, expected, destination):
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                raise ValueError("Runtime archive changed: " + path.name)
        parts = []
        with path.open("rb") as stream:
            while chunk := stream.read(PART_SIZE):
                part = destination + f".part-{len(parts)}"
                await self._sandbox.files.write(part, chunk, request_timeout=180)
                parts.append(part)
        await self.root_command(
            "cat " + " ".join(map(shlex.quote, parts)) + " > " + shlex.quote(destination)
        )
        await self.root_command("rm -- " + " ".join(map(shlex.quote, parts)))

    async def start(self, force_build):
        await super().start(force_build)
        await self.root_command("mkdir -p " + CONTROL)
        bootstrap = json.loads((self._root / "manifests/bootstrap-artifacts.json").read_text())
        await self.upload_archive(
            self._root / "cache/bootstrap/python313.tar.gz",
            bootstrap["python313.tar.gz"]["sha256"],
            CONTROL + "/python.tar.gz",
        )
        await self.root_command(f"tar -xzf {CONTROL}/python.tar.gz -C {CONTROL}")
        module = Path(__file__).with_name("submission_delta.py")
        await self._sandbox.files.write(CONTROL + "/submission_delta.py", module.read_bytes())
        for index, artifact in enumerate(self.entry["archives"]):
            remote = CONTROL + f"/prerequisite-{index}.tar.gz"
            await self.upload_archive(self._root / artifact["archive"], artifact["sha256"], remote)
            await self.root_command("tar -xzf " + shlex.quote(remote) + " -C /", timeout=300)
        if self.entry.get("install_command"):
            await self.root_command(self.entry["install_command"], timeout=300)
        self._runtime_env.update(self.entry.get("env", {}))

    async def begin_actor(self, network_mode, logs_dir):
        self._logs = logs_dir
        self._study_network = network_mode
        offline_env = self.entry.get("offline_env", {}) if network_mode == "offline" else {}
        self._runtime_env.update(offline_env)
        await self._sandbox.update_network(
            {"allow_internet_access": network_mode == "public", "allow_out": []}
        )
        result = await super().exec(
            PYTHON + " -I -S -c " + shlex.quote(NETWORK_PROBE), user=self.actor_user, timeout_sec=25
        )
        checks = json.loads(result.stdout)
        verified = (
            all(not row["reachable"] for row in checks)
            if network_mode == "offline"
            else any(row["reachable"] for row in checks)
        )
        save_json(
            logs_dir / "network.json",
            {
                "mode": network_mode,
                "checks": checks,
                "verified": verified,
                "actor_user": self.actor_user,
                "verifier_mode": network_mode,
                "prerequisites": self.entry,
                "offline_env": offline_env,
            },
        )
        if not verified:
            raise RuntimeError("Full-task actor network check failed")
        code = f"""import json,sys
from pathlib import Path
sys.path.insert(0,{CONTROL!r})
from submission_delta import snapshot
data=snapshot(Path('/'),{self.entry["capture_paths"]!r})
Path({(CONTROL + "/baseline.json")!r}).write_text(json.dumps(data))
"""
        await self.python_command(code, timeout=300)
        baseline = await self._sandbox.files.read(
            CONTROL + "/baseline.json", format="bytes", request_timeout=180
        )
        (logs_dir / "submission").mkdir(parents=True, exist_ok=True)
        (logs_dir / "submission/baseline.json").write_bytes(baseline)
        processes = await self.python_command(PROCESS_SNAPSHOT)
        self._baseline_processes = json.loads(processes.stdout)
        self._scope = ActorCommandScope(self._sandbox.commands)
        self._actor_active = True

    async def _dispatch_command(self, command, *, cwd, env, timeout_sec, user):
        parent = super()._dispatch_command
        if not self._actor_active:
            return await parent(command, cwd=cwd, env=env, timeout_sec=timeout_sec, user=user)
        wrapped, cleanup = process_group_command(self._sandbox, command, python=PYTHON)
        started = monotonic()

        async def launch():
            handle = await parent(
                wrapped, cwd=cwd, env=env, timeout_sec=timeout_sec, user=self.actor_user
            )
            # Encoding the command hides solve.sh from the vendor's pattern check.
            # Restore its reconnect-only handling for long reference commands.
            return oracle_handle(
                handle, self._sandbox.commands, command, timeout_sec, started, self.logger
            )

        handle = await self._scope.dispatch(launch, cleanup)
        self._command_records.append(
            {"sdk_command_id": handle.pid, "identity_file": cleanup.record_path}
        )
        return handle

    async def stop_actor_processes(self):
        if self._scope is not None:
            record = await self._scope.close()
            save_json(self._logs / "command-scope.json", record)

    async def end_actor(self, logs_dir):
        started = monotonic()
        await self.stop_actor_processes()
        self._actor_active = False
        code = f"""import json,sys
from pathlib import Path
sys.path.insert(0,{CONTROL!r})
from submission_delta import capture_delta
baseline=json.loads(Path({(CONTROL + "/baseline.json")!r}).read_text())
archive=Path({(CONTROL + "/submission.tar.gz")!r})
record=capture_delta(Path('/'),{self.entry["capture_paths"]!r},baseline,archive)
parts=[]
with archive.open('rb') as stream:
    while data:=stream.read({PART_SIZE}):
        part=Path(str(archive)+'.part-'+str(len(parts)));part.write_bytes(data);parts.append(str(part))
record['parts']=parts
Path({(CONTROL + "/submission.json")!r}).write_text(json.dumps(record))
"""
        await self.python_command(code, timeout=600)
        manifest = json.loads(await self._sandbox.files.read(CONTROL + "/submission.json"))
        folder = logs_dir / "submission"
        archive = folder / "submission.tar.gz"
        with archive.open("wb") as stream:
            for part in manifest["parts"]:
                stream.write(
                    await self._sandbox.files.read(part, format="bytes", request_timeout=180)
                )
        with archive.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != manifest["sha256"]:
                raise ValueError("Submission delta transfer checksum mismatch")
        manifest.update(
            transfer_verified=True,
            source_fingerprint=self._source_fingerprint,
            template_id=self._template_name,
            prerequisites=self.entry,
            actor_user=self.actor_user,
        )
        save_json(folder / "manifest.json", manifest)
        processes = json.loads((await self.python_command(PROCESS_SNAPSHOT)).stdout)
        baseline_ids = {(row["pid"], row["start_ticks"]) for row in self._baseline_processes}
        save_json(
            folder / "processes.json",
            {
                "baseline": self._baseline_processes,
                "new_at_submission": [
                    row for row in processes if (row["pid"], row["start_ticks"]) not in baseline_ids
                ],
                "actor_commands": self._command_records,
            },
        )
        save_json(logs_dir / "capture-timing.json", {"seconds": monotonic() - started})
        # Required background services remain alive, so an offline trial must not
        # grant them internet access as a side effect of starting the verifier.

    async def _apply_network_policy(self, network_policy):
        if self._study_network is None:
            return await super()._apply_network_policy(network_policy)
        await self._sandbox.update_network(
            {"allow_internet_access": self._study_network == "public", "allow_out": []}
        )

    async def exec(self, command, **kwargs):
        kwargs["env"] = {**self._runtime_env, **(kwargs.get("env") or {})}
        if not self._actor_active and "/tests/test.sh" in command:
            if self._study_verifier_env is None:
                from harnesslab.coding.verifier_cache import prepare_verifier

                self._study_verifier_env = await prepare_verifier(
                    self, self.entry["verifier"], CONTROL, PYTHON
                )
                # The public cache replaces the parent's online dependency transport.
                self._verifier_bootstrap = False
                save_json(self._logs / "verifier-prerequisites.json", self.entry["verifier"])
            kwargs["env"] = {**(kwargs.get("env") or {}), **self._study_verifier_env}
            for name, value in self.entry["verifier"]["env"].items():
                if value is None:
                    kwargs["env"].pop(name, None)
        return await super().exec(command, **kwargs)
