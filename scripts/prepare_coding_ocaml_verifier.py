"""Cache the pinned public OCaml testsuite repository for verifier-only cloning."""

import argparse
import asyncio
import hashlib
import json
import re
import shlex
from pathlib import Path

import certifi

from harnesslab.coding.config import configure_runtime, project_root, save_json

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--dataset", type=Path, required=True)
parser.add_argument("--run", required=True)
args = parser.parse_args()
if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,47}", args.run):
    raise ValueError("Use a short public repository preparation run name")
root = project_root()
configure_runtime(root)
task = "fix-ocaml-gc"
run = args.run
url = "https://github.com/sadiqj/ocaml/"
tag = "tag_purposefully_broken_sweeping_changes"
revision = "356d558bf89552ed9229253ec4135c691234f060"
target = "/opt/harnesslab-verifier-inputs/fix-ocaml-gc/ocaml.git"


async def main():
    from benchmark_next_cleanup import cleanup_run
    from benchmark_next_environment import source_fingerprint
    from harbor.models.task.config import TaskConfig
    from harbor.models.trial.paths import TrialPaths

    from harnesslab.coding.native_environment import CONTROL, NativeStudyEnvironment

    folder = root / "artifacts/coding-verifier-repositories" / run / task
    assert not folder.exists()
    source = args.dataset / "tasks" / task
    provenance = json.loads((args.dataset / "provenance.json").read_text())
    assert provenance["revision"] == "12b7565679ce5006230b820666353673a133db93"
    assert (
        hashlib.sha256((source / "tests/test.sh").read_bytes()).hexdigest()
        == provenance["files"]["tasks/" + task + "/tests/test.sh"]
    )
    spec = TaskConfig.model_validate_toml((source / "task.toml").read_text())
    fingerprint = source_fingerprint(source / "environment", spec.environment)
    profile = folder / "profile.json"
    save_json(
        profile,
        {
            "tasks": {
                task: {
                    "runtime_profile": "native",
                    "source_fingerprint": fingerprint,
                    "capture_paths": ["/app"],
                    "archives": [],
                    "env": {},
                }
            }
        },
    )
    identity = run + "-" + task
    environment = NativeStudyEnvironment(
        environment_dir=source / "environment",
        environment_name=task,
        session_id=identity,
        trial_paths=TrialPaths(trial_dir=folder / "trial"),
        task_env_config=spec.environment,
        profile_file=".env.sandbox",
        image_map="configs/benchmark-images-next.json",
        sandbox_timeout_secs=1800,
        prerequisites_manifest=str(profile.relative_to(root)),
    )
    record = {
        "task": task,
        "model_calls": 0,
        "ok": False,
        "url": url,
        "tag": tag,
        "revision": revision,
        "source_fingerprint": fingerprint,
        "test_script_sha256": hashlib.sha256((source / "tests/test.sh").read_bytes()).hexdigest(),
        "python_downloads": {},
    }
    owned = set()
    try:
        await environment.start(False)
        owned.add(environment._sandbox.sandbox_id)
        record["sandbox_id"] = environment._sandbox.sandbox_id
        save_json(folder / "receipt.json", record)
        ca = CONTROL + "/public-ca.pem"
        await environment._sandbox.files.write(ca, Path(certifi.where()).read_bytes())
        online = dict(
            GIT_SSL_CAINFO=ca,
            GIT_TERMINAL_PROMPT="0",
            GIT_CONFIG_GLOBAL="/dev/null",
            GIT_CONFIG_NOSYSTEM="1",
        )
        download = await environment.exec(
            "mkdir -p "
            + shlex.quote(str(Path(target).parent))
            + " && git -c http.version=HTTP/1.1 clone --bare --depth 1 --branch "
            + shlex.quote(tag)
            + " "
            + shlex.quote(url)
            + " "
            + shlex.quote(target),
            env=online,
            user="root",
            timeout_sec=600,
        )
        (folder / "download.stdout").write_text(download.stdout or "")
        (folder / "download.stderr").write_text(download.stderr or "")
        assert download.return_code == 0, "Public Git repository download failed"
        await environment._sandbox.update_network({"allow_internet_access": False, "allow_out": []})
        code = f"""import hashlib,json,os,subprocess,tarfile
from pathlib import Path
target={target!r};url={url!r};tag={tag!r};revision={revision!r}
env=dict(os.environ,GIT_CONFIG_GLOBAL='/dev/null',GIT_CONFIG_NOSYSTEM='1',GIT_TERMINAL_PROMPT='0')
def git(*args):
    p=subprocess.run(['git',*args],env=env,capture_output=True,text=True,timeout=120)
    assert p.returncode==0,p.stderr
    return p.stdout.strip()
assert git('--git-dir',target,'rev-parse',tag+'^{{commit}}')==revision
git('--git-dir',target,'fsck','--full')
git('-c','protocol.allow=never','-c','protocol.file.allow=always',
    '-c','url.file://'+target+'.insteadOf='+url,'clone',url,'/tmp/ocaml-offline-probe')
git('-C','/tmp/ocaml-offline-probe','checkout',tag)
assert git('-C','/tmp/ocaml-offline-probe','rev-parse','HEAD')==revision
assert Path('/tmp/ocaml-offline-probe/testsuite').is_dir()
archive=Path('/tmp/ocaml-verifier-repository.tar.gz')
with tarfile.open(archive,'w:gz') as stream:stream.add(target,arcname=target.lstrip('/'))
parts=[];digest=hashlib.sha256()
with archive.open('rb') as stream:
    while data:=stream.read(16*1024*1024):
        digest.update(data);part=str(archive)+'.part-'+str(len(parts))
        Path(part).write_bytes(data);parts.append(part)
print(json.dumps({{'sha256':digest.hexdigest(),'bytes':archive.stat().st_size,'parts':parts}}))
"""
        result = await environment.python_command(code, timeout=600)
        (folder / "offline.stdout").write_text(result.stdout or "")
        (folder / "offline.stderr").write_text(result.stderr or "")
        assert result.return_code == 0, "Offline Git clone probe failed"
        info = json.loads(result.stdout.strip().splitlines()[-1])
        archive = folder / "verifier-repository.tar.gz"
        with archive.open("wb") as stream:
            for part in info["parts"]:
                stream.write(
                    await environment._sandbox.files.read(part, format="bytes", request_timeout=180)
                )
        assert hashlib.sha256(archive.read_bytes()).hexdigest() == info["sha256"]
        record.update(
            ok=True,
            offline_clone_verified=True,
            verifier_env={
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "url.file://" + target + ".insteadOf",
                "GIT_CONFIG_VALUE_0": url,
            },
            archive={
                "archive": str(archive.relative_to(root)),
                "sha256": info["sha256"],
                "bytes": info["bytes"],
            },
        )
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if environment._sandbox:
            owned.add(environment._sandbox.sandbox_id)
            try:
                await environment.stop(delete=True)
            except Exception as exc:
                record["stop_error"] = type(exc).__name__
        record["cleanup"] = await asyncio.to_thread(
            cleanup_run, root, identity, profile_file=".env.sandbox", expected_ids=owned
        )
        save_json(folder / "receipt.json", record)
        print(json.dumps(record), flush=True)
    raise SystemExit(0 if record["ok"] and record["cleanup"]["verified"] else 1)


asyncio.run(main())
