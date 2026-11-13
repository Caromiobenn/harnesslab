"""Common task prerequisites and an independently controlled actor network phase."""

from __future__ import annotations

import base64
import hashlib
import json
import shlex
from pathlib import Path
from time import monotonic

from benchmark_next_environment import BenchmarkAliyunEnvironment

from harnesslab.coding.config import save_json

PREFIX = "/opt/harnesslab-prerequisites"
ACTOR = "harnesslab"
ACTOR_UID = 26000

NETWORK_PROBE = r"""import json,socket,urllib.request,urllib.error
results=[]
for url in ('https://example.com','https://api.github.com'):
    try:
        with urllib.request.urlopen(url,timeout=5) as response:
            results.append({'target':url,'reachable':True,'status':response.status})
    except urllib.error.HTTPError as error:
        results.append({'target':url,'reachable':error.code!=403,'status':error.code})
    except Exception as error:
        results.append({'target':url,'reachable':False,'error':type(error).__name__})
try:
    with socket.create_connection(('1.1.1.1',443),timeout=5):
        results.append({'target':'1.1.1.1:443','reachable':True})
except Exception as error:
    results.append({'target':'1.1.1.1:443','reachable':False,'error':type(error).__name__})
print(json.dumps(results))
"""

INSTALL = f"""set -eu
export DEBIAN_FRONTEND=noninteractive
if ls {PREFIX}/debs/*.deb >/dev/null 2>&1; then
  # dpkg configures each layer after unpacking: python3.12-minimal -> python3-minimal -> python3.
  for layer in 1 2 3; do
    if dpkg -i {PREFIX}/debs/*.deb; then break; fi
    test "$layer" -lt 3
  done
fi
if ls {PREFIX}/wheels/*.whl >/dev/null 2>&1; then
  python -m pip install --no-index --find-links={PREFIX}/wheels {PREFIX}/wheels/*.whl
fi
useradd --uid {ACTOR_UID} --create-home --shell /bin/bash {ACTOR}
mkdir -p /app /home/{ACTOR}/.local/bin /usr/local/lib/compcert
chown -R {ACTOR_UID}:{ACTOR_UID} /app /home/{ACTOR} /usr/local/lib/compcert
cp -L "$(command -v python3)" {PREFIX}/controller-python
"""

STOP_ACTOR = """import json,os,signal,time
from pathlib import Path
def active_processes():
    targets=[]
    for folder in Path('/proc').glob('[0-9]*'):
        try:
            fields=dict(line.split(':',1) for line in (folder/'status').read_text().splitlines()
                        if ':' in line)
            uid=int(fields['Uid'].split()[0])
            state=fields['State'].split()[0]
            # A zombie has exited; only its parent's wait/reaping can remove the proc entry.
            if uid==26000 and state not in ('Z','X'):
                targets.append({'pid':int(folder.name),'state':state})
        except (FileNotFoundError,ProcessLookupError): pass
    return targets
for attempt in range(50):
    targets=active_processes()
    if not targets: break
    for target in targets:
        try: os.kill(target['pid'],signal.SIGKILL)
        except ProcessLookupError: pass
    time.sleep(0.1)
else:
    remaining=active_processes()
    if remaining:
        raise RuntimeError('Actor processes still active: '+json.dumps(remaining))
"""

SOURCE_MIRRORS = r"""import json,os,subprocess
from pathlib import Path
prefix=Path('/opt/harnesslab-prerequisites')
entries={'CompCert':('https://github.com/AbsInt/CompCert.git','v3.13.1'),
         'pyknotid':('https://github.com/SPOCKnots/pyknotid.git','0.5.3')}
def run(*args):
    subprocess.run(args,check=True,stdout=subprocess.DEVNULL)
for name,(url,tag) in entries.items():
    source=prefix/'sources'/name
    if not source.exists(): continue
    # A new single-tree commit enables native git clone without exposing upstream history.
    run('git','-C',str(source),'init','--quiet')
    run('git','-C',str(source),'add','.')
    run('git','-C',str(source),'-c','user.name=HarnessLab fixture',
        '-c','user.email=fixture@localhost','commit','--quiet','-m','Public source snapshot')
    run('git','-C',str(source),'tag',tag)
    run('git','config','--system',f'url.file://{source}.insteadOf',url)
    run('git','config','--system','--add','safe.directory',str(source))
    run('git','config','--system','--add','safe.directory',str(source/'.git'))
    if name=='CompCert':
        run('chmod','-R','a+rX',str(prefix/'opam'))
        # The public task includes installing ccomp; allow that target in both arms.
        run('chown','26000:26000','/usr/local/bin')
    if name=='pyknotid':
        import sysconfig
        site=Path(sysconfig.get_path('purelib'))
        run('chown','-R','26000:26000',str(site))
        # pip creates entry points here; the interpreter itself remains root owned.
        run('chown','26000:26000','/usr/local/bin')
"""


class StudyEnvironment(BenchmarkAliyunEnvironment):
    def __init__(self, *args, prerequisites_manifest: str, **kwargs):
        super().__init__(*args, **kwargs)
        manifest = json.loads((self._root / prerequisites_manifest).read_text())
        self._prerequisite = manifest["tasks"][self.environment_name]
        if self._prerequisite["source_fingerprint"] != self._source_fingerprint:
            raise ValueError("Prerequisites refer to a different task environment")
        self._actor_active = False
        self._actor_env = {}

    async def start(self, force_build: bool):
        await super().start(force_build)
        entry = self._prerequisite
        archive = self._root / entry["archive"]
        with archive.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != entry["sha256"]:
                raise ValueError("Public prerequisite archive changed")
        parts = []
        with archive.open("rb") as stream:
            while data := stream.read(16 * 1024 * 1024):
                name = f"/tmp/harnesslab-prerequisite-part-{len(parts):04d}"
                await self._sandbox.files.write(name, data, request_timeout=180)
                parts.append(name)
        await self._root_command(
            "cat " + " ".join(parts) + " > /tmp/harnesslab-prerequisites.tar.gz", 120
        )
        await self._root_command("rm -- " + " ".join(parts), 30)
        await self._root_command("tar -xzf /tmp/harnesslab-prerequisites.tar.gz -C /", 120)
        await self._root_command(INSTALL, 240)
        await self._root_command("python3 -c " + shlex.quote(SOURCE_MIRRORS), 120)
        # The official verifier may download its own packages after the actor has stopped.
        # No verifier or solution files are uploaded during prerequisite preparation.

    async def _root_command(self, command: str, timeout: int = 30):
        result = await super().exec(command, user="root", timeout_sec=timeout)
        if result.return_code:
            raise RuntimeError("Environment preparation failed: " + (result.stderr or "")[-1500:])
        return result

    async def begin_actor(self, network_mode: str, logs_dir: Path):
        if self.environment_name == "compile-compcert":
            result = await super().exec(
                "printf '%s' \"$PATH\"", user=ACTOR, env={"HOME": f"/home/{ACTOR}"}, timeout_sec=30
            )
            if result.return_code or not result.stdout.strip():
                raise RuntimeError("Could not inspect the CompCert actor's shell PATH")
            self._actor_env = {
                "PATH": f"{PREFIX}/opam/toolchain/bin:" + result.stdout.strip(),
                "OPAMROOT": f"{PREFIX}/opam",
                "OPAMSWITCH": "toolchain",
            }
            self._runtime_env.update(self._actor_env)
            save_json(logs_dir / "toolchain-environment.json", self._actor_env)
        await self._sandbox.update_network(
            {"allow_internet_access": network_mode == "public", "allow_out": []}
        )
        self._actor_active = True
        result = await self.exec("python3 -c " + shlex.quote(NETWORK_PROBE), timeout_sec=25)
        checks = json.loads(result.stdout)
        verified = (
            all(not item["reachable"] for item in checks)
            if network_mode == "offline"
            else any(item["reachable"] for item in checks)
        )
        save_json(
            logs_dir / "network.json",
            {
                "mode": network_mode,
                "checks": checks,
                "verified": verified,
                "actor_user": ACTOR,
                "actor_uid": ACTOR_UID,
                "prerequisites": self._prerequisite,
            },
        )
        if not verified:
            raise RuntimeError("Actor network policy did not pass its live check")

    async def stop_actor_processes(self):
        # Kill running tools at the deadline, before waiting for an in-flight API response.
        await self._root_command(f"{PREFIX}/controller-python -I -S -c " + shlex.quote(STOP_ACTOR))

    async def end_actor(self, logs_dir: Path):
        capture_started = monotonic()
        # Stop background actor commands before granting the verifier network access.
        await self.stop_actor_processes()
        self._actor_active = False
        outputs = {
            "cancel-async-tasks": "/app/run.py",
            "db-wal-recovery": "/app/recovered.json",
            "raman-fitting": "/app/results.json",
            "regex-log": "/app/regex.txt",
        }
        target = outputs.get(self.environment_name)
        if target and not await self._sandbox.files.exists(target):
            save_json(logs_dir / "submission/manifest.json", {"path": target, "exists": False})
        if target and await self._sandbox.files.exists(target):
            folder = logs_dir / "submission"
            folder.mkdir(exist_ok=True)
            self._actor_active = True
            try:
                local = folder / Path(target).name
                await self.download_file(target, local)
                data = local.read_bytes()
                save_json(
                    folder / "manifest.json",
                    {
                        "path": target,
                        "exists": True,
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "bytes": len(data),
                    },
                )
            except PermissionError as exc:
                save_json(folder / "manifest.json", {"path": target, "capture_error": str(exc)})
            finally:
                self._actor_active = False
        if self.environment_name in ("compile-compcert", "build-cython-ext"):
            await self.capture_build_submission(logs_dir)
        save_json(logs_dir / "capture-timing.json", {"seconds": monotonic() - capture_started})
        await self._sandbox.update_network({"allow_internet_access": True, "allow_out": []})

    async def capture_build_submission(self, logs_dir: Path):
        code = r"""import hashlib,json,tarfile,sysconfig
from pathlib import Path
paths=['/app','/tmp/CompCert','/usr/local/lib/compcert','/usr/local/bin/ccomp',
       str(Path(sysconfig.get_path('purelib'))/'pyknotid')]
archive=Path('/home/harnesslab/submission.tar.gz')
existing=[name for name in paths if Path(name).exists()]
with tarfile.open(archive,'w:gz',dereference=False) as output:
    for name in existing: output.add(name,arcname=name.lstrip('/'))
parts=[];digest=hashlib.sha256()
with archive.open('rb') as stream:
    while data:=stream.read(16*1024*1024):
        part=Path('/home/harnesslab/submission.part-'+str(len(parts)))
        part.write_bytes(data);parts.append(str(part));digest.update(data)
print(json.dumps({'paths':existing,'parts':parts,'bytes':archive.stat().st_size,
                  'sha256':digest.hexdigest()}))
"""
        self._actor_active = True
        try:
            result = await self.exec(
                f"{PREFIX}/controller-python -I -S -c " + shlex.quote(code), timeout_sec=300
            )
            if result.return_code:
                raise RuntimeError("Submission capture failed: " + (result.stderr or "")[-1000:])
        finally:
            self._actor_active = False
        manifest = json.loads(result.stdout)
        folder = logs_dir / "submission"
        folder.mkdir(exist_ok=True)
        archive = folder / "submission.tar.gz"
        with archive.open("wb") as stream:
            for part in manifest["parts"]:
                stream.write(
                    await self._sandbox.files.read(part, format="bytes", request_timeout=180)
                )
        with archive.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != manifest["sha256"]:
            raise ValueError("Submission archive transfer checksum mismatch")
        manifest.update(archive="submission.tar.gz", transfer_verified=True)
        save_json(folder / "manifest.json", manifest)

    async def exec(self, command, **kwargs):
        if self._actor_active:
            kwargs["user"] = ACTOR
            kwargs["env"] = {
                **self._actor_env,
                **(kwargs.get("env") or {}),
                "HOME": f"/home/{ACTOR}",
            }
        return await super().exec(command, **kwargs)

    async def upload_file(self, source_path, target_path):
        if self._actor_active:
            encoded = base64.b64encode(Path(source_path).read_bytes()).decode()
            code = (
                "import base64;from pathlib import Path;"
                f"Path({target_path!r}).write_bytes(base64.b64decode({encoded!r}))"
            )
            result = await self.exec(
                f"{PREFIX}/controller-python -I -S -c " + shlex.quote(code), timeout_sec=120
            )
            if result.return_code:
                raise PermissionError("Actor file upload failed: " + (result.stderr or "")[-1000:])
            return
        return await super().upload_file(source_path, target_path)

    async def download_file(self, source_path, target_path):
        if self._actor_active:
            code = (
                "import base64;from pathlib import Path;"
                f"print(base64.b64encode(Path({source_path!r}).read_bytes()).decode())"
            )
            result = await self.exec(
                f"{PREFIX}/controller-python -I -S -c " + shlex.quote(code), timeout_sec=120
            )
            if result.return_code:
                raise PermissionError(
                    "Actor file download failed: " + (result.stderr or "")[-1000:]
                )
            Path(target_path).write_bytes(base64.b64decode(result.stdout.strip(), validate=True))
            return
        return await super().download_file(source_path, target_path)
