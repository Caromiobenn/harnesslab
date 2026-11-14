"""Cache pinned public Git inputs and verify ordinary cloning without internet."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import shlex
from pathlib import Path

import certifi

from harnesslab.coding.config import configure_runtime, project_root, save_json
from harnesslab.coding.native_controls import public_cache

PREFIX = "/opt/harnesslab-public-git"


def git_environment(recipe: dict, target: str) -> dict:
    urls = [recipe["url"], *recipe.get("aliases", [])]
    env = {"GIT_CONFIG_COUNT": str(len(urls))}
    for index, url in enumerate(urls):
        env[f"GIT_CONFIG_KEY_{index}"] = "url.file://" + target + ".insteadOf"
        env[f"GIT_CONFIG_VALUE_{index}"] = url
    return env


def download_command(recipe: dict, target: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", recipe["revision"]):
        raise ValueError("Public repositories require a full commit revision")
    git = "git --git-dir=" + shlex.quote(target)
    depth = "" if recipe.get("full_history") else " --depth 1"
    return " && ".join(
        [
            "git init --bare " + shlex.quote(target),
            git
            + " -c http.version=HTTP/1.1 fetch"
            + depth
            + " "
            + shlex.join([recipe["url"], recipe["revision"]]),
            git + " update-ref refs/heads/main " + recipe["revision"],
            git + " symbolic-ref HEAD refs/heads/main",
            *([git + " config uploadpack.allowFilter true"] if recipe.get("full_history") else []),
        ]
    )


def probe_code(recipe: dict, target: str, destination: str) -> str:
    return f"""import json,os,subprocess
from pathlib import Path
env=dict(os.environ,**{git_environment(recipe, target)!r})
def git(*args):
    p=subprocess.run(['git','-c','protocol.allow=never','-c','protocol.file.allow=always',*args],
        env=env,capture_output=True,text=True,timeout=300)
    assert p.returncode==0,p.stderr
    return p.stdout.strip()
git('--git-dir',{target!r},'fsck','--full')
git('clone',*{(["--filter=blob:none"] if recipe.get("full_history") else [])!r},
    {recipe["url"]!r},{destination!r})
git('-C',{destination!r},'checkout',{recipe["revision"]!r})
assert git('-C',{destination!r},'rev-parse','HEAD')=={recipe["revision"]!r}
for name in {recipe["required_paths"]!r}:
    assert (Path({destination!r})/name).exists(),name
print(json.dumps({{'revision':{recipe["revision"]!r},'offline_clone_verified':True,
                  'filtered_clone_verified':{bool(recipe.get("full_history"))!r}}}))
"""


async def prepare_one(root: Path, dataset: Path, run: str, task: str, recipe: dict, ledger: dict):
    from benchmark_next_cleanup import cleanup_run
    from benchmark_next_environment import source_fingerprint
    from harbor.models.task.config import TaskConfig
    from harbor.models.trial.paths import TrialPaths

    from harnesslab.coding.native_environment import CONTROL, NativeStudyEnvironment

    folder = root / "artifacts/coding-public-git" / run / task
    if folder.exists():
        raise ValueError("Inspect the existing public Git preparation before a new run")
    source = dataset / "tasks" / task
    provenance = json.loads((dataset / "provenance.json").read_text())
    spec = TaskConfig.model_validate_toml((source / "task.toml").read_text())
    fingerprint = source_fingerprint(source / "environment", spec.environment)
    entry = {
        "runtime_profile": "native",
        "source_fingerprint": fingerprint,
        "capture_paths": ["/app"],
        "archives": [],
        "env": {},
    }
    system = None
    if recipe.get("system_packages"):
        system = public_cache(root, ledger["families"]["actor_system"][task])
        if system["source_fingerprint"] != fingerprint:
            raise ValueError("Public system cache belongs to another task image")
        entry.update(archives=[system["archive"]], env=system["env"])
    profile = folder / "profile.json"
    save_json(profile, {"tasks": {task: entry}})
    identity = run + "-git-" + task
    environment = NativeStudyEnvironment(
        environment_dir=source / "environment",
        environment_name=task,
        session_id=identity,
        trial_paths=TrialPaths(trial_dir=folder / "trial"),
        task_env_config=spec.environment,
        profile_file=".env.sandbox",
        image_map="configs/benchmark-images-next.json",
        sandbox_timeout_secs=3600,
        prerequisites_manifest=str(profile.relative_to(root)),
    )
    record = {
        "task": task,
        "recipe": recipe,
        "source_fingerprint": fingerprint,
        "benchmark_revision": provenance["revision"],
        "model_calls": 0,
        "ok": False,
    }
    owned = set()
    target = PREFIX + "/" + task + ".git"
    try:
        await environment.start(False)
        owned.add(environment._sandbox.sandbox_id)
        record["sandbox_id"] = environment._sandbox.sandbox_id
        save_json(folder / "receipt.json", record)
        if system:
            await environment._sandbox.update_network(
                {"allow_internet_access": False, "allow_out": []}
            )
            result = await environment.exec(
                "apt-get update -qq && apt-get install -y " + shlex.join(recipe["system_packages"]),
                env=system["offline_env"],
                user="root",
                timeout_sec=600,
            )
            (folder / "install.stdout").write_text(result.stdout or "")
            (folder / "install.stderr").write_text(result.stderr or "")
            if result.return_code:
                raise RuntimeError("Offline Git installer preparation failed")
            await environment._sandbox.update_network(
                {"allow_internet_access": True, "allow_out": []}
            )
        ca = CONTROL + "/public-git-ca.pem"
        await environment._sandbox.files.write(ca, Path(certifi.where()).read_bytes())
        result = await environment.exec(
            download_command(recipe, target),
            env={
                "GIT_SSL_CAINFO": ca,
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_CONFIG_GLOBAL": "/dev/null",
                "GIT_CONFIG_NOSYSTEM": "1",
            },
            user="root",
            timeout_sec=1800,
        )
        (folder / "download.stdout").write_text(result.stdout or "")
        (folder / "download.stderr").write_text(result.stderr or "")
        if result.return_code:
            raise RuntimeError("Pinned public Git download failed")
        await environment._sandbox.update_network({"allow_internet_access": False, "allow_out": []})
        code = probe_code(recipe, target, "/tmp/harnesslab-public-git-probe")
        result = await environment.python_command(code, timeout=600)
        (folder / "offline.stdout").write_text(result.stdout or "")
        (folder / "offline.stderr").write_text(result.stderr or "")
        if result.return_code:
            raise RuntimeError("Pinned public Git offline clone failed")
        record["offline_probe"] = json.loads(result.stdout.strip().splitlines()[-1])
        code = f"""import hashlib,json,tarfile
from pathlib import Path
archive=Path('/tmp/public-git.tar.gz')
with tarfile.open(archive,'w:gz') as stream:stream.add({target!r},arcname={target.lstrip("/")!r})
parts=[];digest=hashlib.sha256()
with archive.open('rb') as stream:
    while data:=stream.read(16*1024*1024):
        digest.update(data);part=str(archive)+'.part-'+str(len(parts))
        Path(part).write_bytes(data);parts.append(part)
print(json.dumps({{'sha256':digest.hexdigest(),'bytes':archive.stat().st_size,'parts':parts}}))
"""
        result = await environment.python_command(code, timeout=600)
        if result.return_code:
            raise RuntimeError("Public Git archive creation failed")
        info = json.loads(result.stdout)
        archive = folder / "public-git.tar.gz"
        with archive.open("wb") as stream:
            for part in info["parts"]:
                stream.write(
                    await environment._sandbox.files.read(part, format="bytes", request_timeout=180)
                )
        with archive.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != info["sha256"]:
                raise ValueError("Transferred public Git archive changed")
        record.update(
            ok=True,
            env=git_environment(recipe, target),
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
    return record


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--cache-ledger", type=Path, required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--tasks", nargs="+", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,47}", args.run):
        raise ValueError("Use a short public repository preparation run name")
    root = project_root()
    configure_runtime(root)
    os.environ.pop("BENCHMARK_NEXT_RUN", None)
    profiles = json.loads((root / "configs/coding-public-git.json").read_text())
    ledger = json.loads(args.cache_ledger.read_text())
    provenance = json.loads((args.dataset / "provenance.json").read_text())
    if not profiles["benchmark_revision"] == ledger["benchmark_revision"] == provenance["revision"]:
        raise ValueError("Public Git inputs belong to a different task revision")
    for task in args.tasks:
        for relative in ("instruction.md", "environment/Dockerfile"):
            name = "tasks/" + task + "/" + relative
            if (
                hashlib.sha256((args.dataset / name).read_bytes()).hexdigest()
                != provenance["files"][name]
            ):
                raise ValueError("Pinned task source changed")
    gate = asyncio.Semaphore(2)

    async def one(task):
        async with gate:
            return await prepare_one(
                root, args.dataset, args.run, task, profiles["tasks"][task], ledger
            )

    results = await asyncio.gather(*(one(task) for task in args.tasks))
    save_json(
        root / "artifacts/coding-public-git" / args.run / "summary.json",
        {"model_calls": 0, "results": results},
    )
    raise SystemExit(0 if all(row["ok"] and row["cleanup"]["verified"] for row in results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
