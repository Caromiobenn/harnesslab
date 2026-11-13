"""Cache public Python installers without pre-installing an agent's task dependencies."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import shlex
from pathlib import Path

from harnesslab.coding.config import configure_runtime, project_root, save_json

PREFIX = "/opt/harnesslab-public-wheels"
PART_SIZE = 16 * 1024 * 1024


def package_commands(python: str, recipe: dict) -> tuple[str, str, dict]:
    packages = recipe["packages"]
    if not packages or any(
        not re.fullmatch(r"[A-Za-z0-9_.-]+==[A-Za-z0-9_.+-]+", item) for item in packages
    ):
        raise ValueError("Actor cache packages require explicit public version pins")
    names = shlex.join(packages)
    checks = (
        "import importlib,json;from importlib.metadata import version;"
        + "[importlib.import_module(name) for name in "
        + repr(recipe["import_modules"])
        + "];print(json.dumps({name:version(name) for name in "
        + repr([item.split("==")[0] for item in packages])
        + "}))"
    )
    # Preserve the usual pip command. Local candidates work offline without disabling
    # the public index in the online arm or installing packages before the actor.
    env = {
        "PIP_FIND_LINKS": PREFIX,
        "PIP_RETRIES": "0",
        "PIP_TIMEOUT": "5",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
    }
    return (
        f"{shlex.quote(python)} -m pip download --dest {PREFIX} {names}",
        f"{shlex.quote(python)} -m pip install {names} && "
        f"{shlex.quote(python)} -c {shlex.quote(checks)}",
        env,
    )


async def prepare_one(root: Path, dataset: Path, run: str, task: str, recipe: dict) -> dict:
    from benchmark_next_cleanup import cleanup_run
    from benchmark_next_environment import source_fingerprint
    from harbor.models.task.config import TaskConfig
    from harbor.models.trial.paths import TrialPaths

    from harnesslab.coding.native_environment import NativeStudyEnvironment

    source = dataset / "tasks" / task
    provenance = json.loads((dataset / "provenance.json").read_text())
    spec = TaskConfig.model_validate_toml((source / "task.toml").read_text())
    fingerprint = source_fingerprint(source / "environment", spec.environment)
    instruction_sha = hashlib.sha256((source / "instruction.md").read_bytes()).hexdigest()
    if instruction_sha != provenance["files"][f"tasks/{task}/instruction.md"]:
        raise ValueError("Task instruction source changed")
    folder = root / "artifacts/coding-actor-wheels" / run / task
    if folder.exists():
        raise ValueError("Inspect the previous preparation before selecting another run")
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
        sandbox_timeout_secs=3600,
        prerequisites_manifest=str(profile.relative_to(root)),
    )
    result = {
        "task": task,
        "recipe": recipe,
        "source_fingerprint": fingerprint,
        "benchmark_revision": provenance["revision"],
        "instruction_sha256": instruction_sha,
        "model_calls": 0,
        "ok": False,
    }
    owned = set()
    try:
        await environment.start(False)
        owned.add(environment._sandbox.sandbox_id)
        result["sandbox_id"] = environment._sandbox.sandbox_id
        save_json(folder / "receipt.json", result)
        python = (await environment.root_command("command -v python")).stdout.strip()
        online_command, offline_command, env = package_commands(python, recipe)
        await environment.root_command("mkdir -p " + PREFIX)
        (folder / "prepare.sh").write_text(online_command + "\n")
        online = await environment.exec(online_command, timeout_sec=1200)
        (folder / "prepare.stdout").write_text(online.stdout or "")
        (folder / "prepare.stderr").write_text(online.stderr or "")
        if online.return_code:
            raise RuntimeError("Public actor dependency download failed")
        await environment._sandbox.update_network({"allow_internet_access": False, "allow_out": []})
        (folder / "offline.sh").write_text(offline_command + "\n")
        offline = await environment.exec(offline_command, env=env, timeout_sec=600)
        (folder / "offline.stdout").write_text(offline.stdout or "")
        (folder / "offline.stderr").write_text(offline.stderr or "")
        if offline.return_code:
            raise RuntimeError("Public actor packages did not install and import offline")
        result["offline_probe"] = {"return_code": 0, "stdout": offline.stdout[-1200:]}
        inspect_code = (
            "import json,sys;from importlib.metadata import distributions;"
            "print(json.dumps({'python':sys.version,'packages':"
            "sorted((d.metadata['Name'],d.version) for d in distributions())}))"
        )
        result["resolved_environment"] = json.loads(
            (
                await environment.root_command(
                    shlex.quote(python) + " -c " + shlex.quote(inspect_code)
                )
            ).stdout
        )
        archive_code = f"""import hashlib,json,tarfile
from pathlib import Path
prefix=Path({PREFIX!r});files={{}}
for path in prefix.iterdir():
    with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    files[path.name]={{'sha256':digest,'bytes':path.stat().st_size}}
archive=Path('/tmp/actor-wheels.tar.gz')
with tarfile.open(archive,'w:gz') as stream:stream.add(prefix,arcname=str(prefix).lstrip('/'))
parts=[]
with archive.open('rb') as stream:
    while data:=stream.read({PART_SIZE}):
        path=str(archive)+'.part-'+str(len(parts));Path(path).write_bytes(data);parts.append(path)
with archive.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
print(json.dumps({{'sha256':digest,'bytes':archive.stat().st_size,'parts':parts,'files':files}}))
"""
        info = json.loads((await environment.python_command(archive_code, timeout=600)).stdout)
        archive = folder / "actor-wheels.tar.gz"
        with archive.open("wb") as stream:
            for part in info["parts"]:
                stream.write(
                    await environment._sandbox.files.read(part, format="bytes", request_timeout=180)
                )
        with archive.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != info["sha256"]:
                raise ValueError("Transferred public wheel archive changed")
        result.update(
            ok=True,
            files=info["files"],
            env=env,
            archive={
                "archive": str(archive.relative_to(root)),
                "sha256": info["sha256"],
                "bytes": info["bytes"],
            },
        )
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if environment._sandbox:
            owned.add(environment._sandbox.sandbox_id)
            try:
                await environment.stop(delete=True)
            except Exception as exc:
                result["stop_error"] = type(exc).__name__
        result["cleanup"] = await asyncio.to_thread(
            cleanup_run, root, identity, profile_file=".env.sandbox", expected_ids=owned
        )
        save_json(folder / "receipt.json", result)
        print(
            json.dumps(
                {key: result.get(key) for key in ("task", "ok", "archive", "error", "cleanup")}
            ),
            flush=True,
        )
    return result


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--tasks", nargs="+", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,47}", args.run):
        raise ValueError("Use a short preparation run name")
    root = project_root()
    configure_runtime(root)
    os.environ.pop("BENCHMARK_NEXT_RUN", None)
    profiles = json.loads((root / "configs/coding-actor-packages.json").read_text())
    provenance = json.loads((args.dataset / "provenance.json").read_text())
    if profiles["benchmark_revision"] != provenance["revision"]:
        raise ValueError("Package profiles belong to a different task revision")
    gate = asyncio.Semaphore(2)

    async def one(task):
        async with gate:
            return await prepare_one(root, args.dataset, args.run, task, profiles["tasks"][task])

    results = await asyncio.gather(*(one(task) for task in args.tasks))
    save_json(
        root / "artifacts/coding-actor-wheels" / args.run / "summary.json",
        {"model_calls": 0, "results": results},
    )
    raise SystemExit(0 if all(row["ok"] and row["cleanup"]["verified"] for row in results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
