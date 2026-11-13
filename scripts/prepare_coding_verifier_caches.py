"""Build shared public verifier caches in fresh cloud instances, with no model calls."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import shlex
import tarfile
from pathlib import Path
from time import monotonic

from harnesslab.coding.cache_recipes import recipe_inventory
from harnesslab.coding.config import configure_runtime, project_root, save_json

REVISION = "12b7565679ce5006230b820666353673a133db93"
VERIFY = "/opt/harnesslab-verifier-cache"
BOOT = "/opt/benchmark-next-verifier"
PART_SIZE = 16 * 1024 * 1024


def pinned_installer(root: Path) -> tuple[bytes, dict]:
    checkout = Path(__file__).resolve().parents[1]
    manifest = json.loads((checkout / "configs/coding-native-pypi.lock.json").read_text())
    verifier = manifest["tasks"]["pypi-server"]["verifier"]
    artifact = verifier["archives"][0]
    path = root / artifact["archive"]
    with path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != artifact["sha256"]:
            raise ValueError("The accepted public verifier cache changed")
    url, spec = next(iter(verifier["downloads"].items()))
    with tarfile.open(path) as archive:
        data = archive.extractfile(spec["path"].lstrip("/")).read()
    if hashlib.sha256(data).hexdigest() != spec["sha256"]:
        raise ValueError("Pinned public installer checksum mismatch")
    return data, {url: spec}


async def prepare_one(root: Path, dataset: Path, run: str, key: str, recipe: dict) -> dict:
    from benchmark_next_bootstrap import prepare_tb21, verifier_environment
    from benchmark_next_cleanup import cleanup_run
    from benchmark_next_environment import source_fingerprint
    from harbor.models.task.config import TaskConfig
    from harbor.models.trial.paths import TrialPaths

    from harnesslab.coding.native_environment import NativeStudyEnvironment

    folder = root / "artifacts/coding-verifier-caches" / run / key
    folder.mkdir(parents=True, exist_ok=True)
    receipt = folder / "receipt.json"
    if receipt.exists():
        saved = json.loads(receipt.read_text())
        if saved["recipe"] != recipe:
            raise ValueError("Cache recipe changed; select a new preparation run")
        if saved["ok"] and saved["cleanup"]["verified"]:
            with (root / saved["archive"]["archive"]).open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() == saved["archive"]["sha256"]:
                    return saved
        raise ValueError("Inspect incomplete cache preparation before starting another run")
    source = dataset / "tasks/pypi-server"
    spec = TaskConfig.model_validate_toml((source / "task.toml").read_text())
    profile = folder / "profile.json"
    save_json(
        profile,
        {
            "tasks": {
                "pypi-server": {
                    "runtime_profile": "native",
                    "source_fingerprint": source_fingerprint(
                        source / "environment", spec.environment
                    ),
                    "capture_paths": ["/app"],
                    "archives": [],
                }
            }
        },
    )
    identity = run + "-" + key
    environment = NativeStudyEnvironment(
        environment_dir=source / "environment",
        environment_name="pypi-server",
        session_id=identity,
        trial_paths=TrialPaths(trial_dir=folder / "trial"),
        task_env_config=spec.environment,
        profile_file=".env.sandbox",
        image_map="configs/benchmark-images-next.json",
        sandbox_timeout_secs=7200,
        prerequisites_manifest=str(profile.relative_to(root)),
    )
    result = {"recipe_id": key, "recipe": recipe, "ok": False, "model_calls": 0}
    owned = set()
    try:
        await environment.start(False)
        owned.add(environment._sandbox.sandbox_id)
        result["sandbox_id"] = environment._sandbox.sandbox_id
        save_json(receipt, result)
        (root / "cache/tmp").mkdir(parents=True, exist_ok=True)
        await prepare_tb21(root, environment)
        await environment.root_command(f"mkdir -p {VERIFY}/downloads")
        data, downloads = pinned_installer(root)
        await environment._sandbox.files.write(VERIFY + "/downloads/uv-install.sh", data)
        await environment._sandbox.files.write(
            VERIFY + "/apt.conf", 'Dir::Etc::sourcelist "/dev/null";\nDir::Etc::sourceparts "-";\n'
        )
        args = [
            BOOT + "/uv-x86_64-unknown-linux-gnu/uvx",
            *recipe["args"][1:],
            "pytest",
            "--version",
        ]
        env = {**verifier_environment(), "UV_CACHE_DIR": VERIFY + "/uv"}
        command = shlex.join(args)
        script = (
            "#!/bin/bash\n"
            + command
            + " > /tmp/cache-prepare.log 2>&1\necho $? > /tmp/cache-prepare.exit\n"
        )
        await environment._sandbox.files.write("/tmp/cache-prepare.sh", script)
        launch = await environment.exec(
            "nohup bash /tmp/cache-prepare.sh >/dev/null 2>&1 </dev/null &", env=env, timeout_sec=30
        )
        if launch.return_code:
            raise RuntimeError("Could not start public dependency preparation")
        started = monotonic()
        while monotonic() - started < 5400:
            if await environment._sandbox.files.exists("/tmp/cache-prepare.exit"):
                break
            await asyncio.sleep(10)
        else:
            raise TimeoutError("Public cache preparation exceeded 5400 seconds")
        await environment.download_file("/tmp/cache-prepare.log", folder / "prepare.log")
        code = int(await environment._sandbox.files.read("/tmp/cache-prepare.exit"))
        if code:
            raise RuntimeError("Public dependency resolution failed; see prepare.log")
        await environment._sandbox.update_network({"allow_internet_access": False, "allow_out": []})
        offline = await environment.exec(command, env={**env, "UV_OFFLINE": "1"}, timeout_sec=180)
        (folder / "offline.stdout").write_text(offline.stdout or "")
        (folder / "offline.stderr").write_text(offline.stderr or "")
        if offline.return_code or "pytest " not in (offline.stdout or ""):
            raise RuntimeError("The prepared package environment did not start offline")
        result["offline_probe"] = {
            "return_code": offline.return_code,
            "stdout": offline.stdout.strip(),
        }
        info_code = f"""import json,tarfile,hashlib
from pathlib import Path
from importlib.metadata import distributions
prefix=Path({VERIFY!r});versions=[]
for path in (prefix/'uv/archive-v0').glob('*'):
    for item in distributions(path=[str(path)]):
        versions.append({{'name':item.metadata['Name'],'version':item.version}})
(prefix/'distributions.json').write_text(json.dumps(versions,sort_keys=True))
paths=[prefix,Path({(BOOT + "/managed-python")!r})]
archive=Path('/tmp/verifier-cache.tar.gz')
with tarfile.open(archive,'w:gz',dereference=False) as stream:
    for path in paths:
        if path.exists(): stream.add(path,arcname=str(path).lstrip('/'))
parts=[]
with archive.open('rb') as stream:
    while data:=stream.read({PART_SIZE}):
        part=str(archive)+'.part-'+str(len(parts));Path(part).write_bytes(data);parts.append(part)
with archive.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
print(json.dumps({{'parts':parts,'sha256':sha,'bytes':archive.stat().st_size,'distributions':versions}}))
"""
        info = json.loads((await environment.python_command(info_code, timeout=900)).stdout)
        archive = folder / "verifier.tar.gz"
        with archive.open("wb") as stream:
            for part in info["parts"]:
                stream.write(
                    await environment._sandbox.files.read(part, format="bytes", request_timeout=180)
                )
        with archive.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != info["sha256"]:
                raise ValueError("Transferred cache checksum mismatch")
        result.update(
            ok=True,
            archive={
                "archive": str(archive.relative_to(root)),
                "sha256": info["sha256"],
                "bytes": info["bytes"],
            },
            distributions=info["distributions"],
            downloads=downloads,
            env={**env, "UV_OFFLINE": "1", "APT_CONFIG": VERIFY + "/apt.conf"},
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
        save_json(receipt, result)
        print(
            json.dumps(
                {
                    key: result.get(key)
                    for key in ("recipe_id", "ok", "archive", "offline_probe", "error", "cleanup")
                }
            ),
            flush=True,
        )
    return result


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--tasks", nargs="+")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,47}", args.run):
        raise ValueError("Use a short preparation run name")
    root = project_root()
    configure_runtime(root)
    os.environ.pop("BENCHMARK_NEXT_RUN", None)
    inventory = recipe_inventory(args.dataset, REVISION)
    selected = {
        key: row
        for key, row in inventory["groups"].items()
        if args.tasks is None or set(row["tasks"]) & set(args.tasks)
    }
    supported = {task for row in inventory["groups"].values() for task in row["tasks"]}
    if args.tasks and set(args.tasks) - supported:
        raise ValueError(
            "No uvx verifier recipe for: " + ", ".join(sorted(set(args.tasks) - supported))
        )
    if not selected:
        raise ValueError("No verifier recipes selected")
    folder = root / "artifacts/coding-verifier-caches" / args.run
    inventory_path = folder / "inventory.json"
    if inventory_path.exists() and json.loads(inventory_path.read_text()) != inventory:
        raise ValueError("Source inventory changed; select a new preparation run")
    save_json(inventory_path, inventory)
    gate = asyncio.Semaphore(2)

    async def one(key, recipe):
        async with gate:
            return await prepare_one(root, args.dataset, args.run, key, recipe)

    results = await asyncio.gather(*(one(key, recipe) for key, recipe in selected.items()))
    save_json(
        folder / "summary.json",
        {"model_calls": 0, "results": results, "custom_tasks": inventory["custom"]},
    )
    raise SystemExit(0 if all(row["ok"] and row["cleanup"]["verified"] for row in results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
