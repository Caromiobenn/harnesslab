"""Cache the official pip and virtual-environment verifier requirements in task images."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import shlex
from pathlib import Path

from prepare_coding_verifier_caches import BOOT, PART_SIZE, REVISION, VERIFY, pinned_installer

from harnesslab.coding.config import configure_runtime, project_root, save_json


def requirements(script: str) -> dict:
    lines = script.replace("\\\n", " ").splitlines()
    commands = [
        shlex.split(line) for line in lines if line.startswith(("pip install ", "uv pip install "))
    ]
    if len(commands) != 1:
        raise ValueError("Expected one explicit verifier package installation")
    command = commands[0]
    kind = "uv-venv" if command[:2] == ["uv", "pip"] else "pip"
    packages = command[3:] if kind == "uv-venv" else command[2:]
    flags = [value for value in packages if value == "--break-system-packages"]
    packages = [value for value in packages if value not in flags]
    if not packages or any(
        not re.fullmatch(r"[A-Za-z0-9_.-]+==[A-Za-z0-9_.+-]+", value) for value in packages
    ):
        raise ValueError("Verifier packages must be explicit version pins")
    recipe = {"kind": kind, "packages": packages, "install_flags": flags}
    if kind == "uv-venv":
        match = re.search(r"^uv venv -p ([0-9.]+) ", script, re.MULTILINE)
        if not match:
            raise ValueError("Expected the verifier's explicit Python version")
        recipe["python"] = match.group(1)
    return recipe


async def prepare_one(root: Path, dataset: Path, run: str, task: str) -> dict:
    from benchmark_next_bootstrap import prepare_tb21, verifier_environment
    from benchmark_next_cleanup import cleanup_run
    from benchmark_next_environment import source_fingerprint
    from harbor.models.task.config import TaskConfig
    from harbor.models.trial.paths import TrialPaths

    from harnesslab.coding.native_environment import NativeStudyEnvironment

    source = dataset / "tasks" / task
    test_script = source / "tests/test.sh"
    provenance = json.loads((dataset / "provenance.json").read_text())
    source_sha = hashlib.sha256(test_script.read_bytes()).hexdigest()
    if (
        provenance["revision"] != REVISION
        or source_sha != provenance["files"][test_script.relative_to(dataset).as_posix()]
    ):
        raise ValueError("Official task source changed")
    recipe = requirements(test_script.read_text())
    spec = TaskConfig.model_validate_toml((source / "task.toml").read_text())
    fingerprint = source_fingerprint(source / "environment", spec.environment)
    folder = root / "artifacts/coding-custom-verifier-caches" / run / task
    receipt = folder / "receipt.json"
    if receipt.exists():
        saved = json.loads(receipt.read_text())
        if (
            saved["recipe"] == recipe
            and saved["source_fingerprint"] == fingerprint
            and saved["ok"]
            and saved["cleanup"]["verified"]
        ):
            with (root / saved["archive"]["archive"]).open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() == saved["archive"]["sha256"]:
                    return saved
        raise ValueError("Inspect previous preparation before selecting a new run")
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
        sandbox_timeout_secs=2400,
        prerequisites_manifest=str(profile.relative_to(root)),
    )
    result = {
        "task": task,
        "recipe": recipe,
        "source_fingerprint": fingerprint,
        "test_script_sha256": source_sha,
        "model_calls": 0,
        "ok": False,
    }
    owned = set()
    try:
        await environment.start(False)
        owned.add(environment._sandbox.sandbox_id)
        result["sandbox_id"] = environment._sandbox.sandbox_id
        save_json(receipt, result)
        await prepare_tb21(root, environment)
        await environment.root_command(f"mkdir -p {VERIFY}/downloads {VERIFY}/wheels")
        await environment._sandbox.files.write(
            VERIFY + "/apt.conf", 'Dir::Etc::sourcelist "/dev/null";\nDir::Etc::sourceparts "-";\n'
        )
        packages = shlex.join(recipe["packages"])
        downloads = {}
        if recipe["kind"] == "pip":
            python = (await environment.root_command("command -v python")).stdout.strip()
            online_command = f"{python} -m pip download --dest {VERIFY}/wheels {packages}"
            offline_command = (
                f"{python} -m pip install --no-index --find-links={VERIFY}/wheels {packages} "
                + shlex.join(recipe["install_flags"])
                + f" && {python} -m pytest --version"
            )
            env = {
                "PIP_NO_INDEX": "1",
                "PIP_FIND_LINKS": VERIFY + "/wheels",
                "APT_CONFIG": VERIFY + "/apt.conf",
            }
            online_env = {}
            inspect_python = python
        else:
            data, downloads = pinned_installer(root)
            await environment._sandbox.files.write(VERIFY + "/downloads/uv-install.sh", data)
            uv = BOOT + "/uv-x86_64-unknown-linux-gnu/uv"
            version = shlex.quote(recipe["python"])
            online_env = {**verifier_environment(), "UV_CACHE_DIR": VERIFY + "/uv"}
            online_command = (
                f"{uv} venv -p {version} /tmp/verifier-cache-online && "
                f"{uv} pip install --python /tmp/verifier-cache-online/bin/python {packages}"
            )
            offline_command = (
                f"{uv} venv -p {version} /tmp/verifier-cache-offline && "
                f"{uv} pip install --python /tmp/verifier-cache-offline/bin/python {packages} && "
                "/tmp/verifier-cache-offline/bin/python -m pytest --version"
            )
            env = {**online_env, "UV_OFFLINE": "1", "APT_CONFIG": VERIFY + "/apt.conf"}
            inspect_python = "/tmp/verifier-cache-offline/bin/python"
        (folder / "prepare.sh").write_text(online_command + "\n")
        online = await environment.exec(online_command, env=online_env, timeout_sec=900)
        (folder / "prepare.stdout").write_text(online.stdout or "")
        (folder / "prepare.stderr").write_text(online.stderr or "")
        if online.return_code:
            raise RuntimeError("Verifier package preparation failed; see logs")
        await environment._sandbox.update_network({"allow_internet_access": False, "allow_out": []})
        offline = await environment.exec(offline_command, env=env, timeout_sec=300)
        (folder / "offline.sh").write_text(offline_command + "\n")
        (folder / "offline.stdout").write_text(offline.stdout or "")
        (folder / "offline.stderr").write_text(offline.stderr or "")
        if offline.return_code or "pytest " not in (offline.stdout or ""):
            raise RuntimeError("Verifier packages did not install and start offline")
        version_code = (
            "import json,sys;from importlib.metadata import distributions;"
            "print(json.dumps({'python':sys.version,'packages':"
            "sorted((d.metadata['Name'],d.version) for d in distributions())}))"
        )
        versions = json.loads(
            (
                await environment.root_command(inspect_python + " -c " + shlex.quote(version_code))
            ).stdout
        )
        result.update(
            offline_probe={"return_code": offline.return_code, "stdout": offline.stdout[-1000:]},
            resolved_environment=versions,
        )
        archive_code = f"""import hashlib,json,tarfile
from pathlib import Path
prefix=Path({VERIFY!r});files={{}}
for path in (prefix/'wheels').glob('*'):
    with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    files[path.name]={{'sha256':digest,'bytes':path.stat().st_size}}
archive=Path('/tmp/custom-verifier-cache.tar.gz')
with tarfile.open(archive,'w:gz',dereference=False) as stream:
    for path in (prefix,Path({(BOOT + "/managed-python")!r})):
        if path.exists():stream.add(path,arcname=str(path).lstrip('/'))
parts=[]
with archive.open('rb') as stream:
    while data:=stream.read({PART_SIZE}):
        path=str(archive)+'.part-'+str(len(parts));Path(path).write_bytes(data);parts.append(path)
with archive.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
print(json.dumps({{'sha256':digest,'bytes':archive.stat().st_size,'parts':parts,'files':files}}))
"""
        info = json.loads((await environment.python_command(archive_code, timeout=600)).stdout)
        archive = folder / "verifier.tar.gz"
        with archive.open("wb") as stream:
            for part in info["parts"]:
                stream.write(
                    await environment._sandbox.files.read(part, format="bytes", request_timeout=180)
                )
        with archive.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != info["sha256"]:
                raise ValueError("Transferred verifier cache checksum mismatch")
        result.update(
            ok=True,
            archive={
                "archive": str(archive.relative_to(root)),
                "sha256": info["sha256"],
                "bytes": info["bytes"],
            },
            files=info["files"],
            downloads=downloads,
            env=env,
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
    gate = asyncio.Semaphore(2)

    async def one(task):
        async with gate:
            return await prepare_one(root, args.dataset, args.run, task)

    results = await asyncio.gather(*(one(task) for task in args.tasks))
    save_json(
        root / "artifacts/coding-custom-verifier-caches" / args.run / "summary.json",
        {"model_calls": 0, "results": results},
    )
    raise SystemExit(0 if all(row["ok"] and row["cleanup"]["verified"] for row in results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
