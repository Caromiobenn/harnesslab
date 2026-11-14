"""Cache public release downloads and verify ordinary commands without internet."""

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
from harnesslab.coding.public_downloads import wget_wrapper
from harnesslab.coding.verifier_cache import curl_wrapper

PREFIX = "/opt/harnesslab-public-downloads"
PART_SIZE = 16 * 1024 * 1024


def download_code(recipe, ca):
    return f"""import hashlib,json,shutil,ssl,tarfile,urllib.request
from pathlib import Path
prefix=Path({PREFIX!r});(prefix/'files').mkdir(parents=True,exist_ok=True)
records={{}};downloads={{}}
context=ssl.create_default_context(cafile={ca!r})
for item in {recipe["files"]!r}:
    path=prefix/'files'/item['name']
    assert path.parent==prefix/'files'
    with urllib.request.urlopen(item['url'],context=context,timeout=120) as response:
        with path.open('wb') as stream:shutil.copyfileobj(response,stream)
    if item.get('tar_version'):
        spec=item['tar_version']
        with tarfile.open(path) as archive:
            assert archive.extractfile(spec['member']).read().decode().strip()==spec['value']
    with path.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
    if item.get('sha256'):assert sha==item['sha256']
    records[item['name']]={{'url':item['url'],'sha256':sha,'bytes':path.stat().st_size}}
    for url in [item['url'],*item.get('aliases',[])]:
        downloads[url]={{'path':str(path),'sha256':sha}}
print(json.dumps({{'files':records,'downloads':downloads}}))
"""


async def prepare_one(root, dataset, run, task, recipe):
    from benchmark_next_cleanup import cleanup_run
    from benchmark_next_environment import source_fingerprint
    from harbor.models.task.config import TaskConfig
    from harbor.models.trial.paths import TrialPaths

    from harnesslab.coding.native_environment import CONTROL, PYTHON, NativeStudyEnvironment

    source = dataset / "tasks" / task
    provenance = json.loads((dataset / "provenance.json").read_text())
    spec = TaskConfig.model_validate_toml((source / "task.toml").read_text())
    fingerprint = source_fingerprint(source / "environment", spec.environment)
    folder = root / "artifacts/coding-public-downloads" / run / task
    if folder.exists():
        raise ValueError("Inspect the previous public download preparation before a new run")
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
    identity = run + "-downloads-" + task
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
        "benchmark_revision": provenance["revision"],
        "source_fingerprint": fingerprint,
        "model_calls": 0,
        "ok": False,
    }
    owned = set()
    try:
        await environment.start(False)
        owned.add(environment._sandbox.sandbox_id)
        record["sandbox_id"] = environment._sandbox.sandbox_id
        save_json(folder / "receipt.json", record)
        ca = CONTROL + "/public-release-ca.pem"
        await environment._sandbox.files.write(ca, Path(certifi.where()).read_bytes())
        code = download_code(recipe, ca)
        (folder / "download.py").write_text(code)
        result = await environment.python_command(code, timeout=1200)
        content = json.loads(result.stdout)
        record.update(content)
        tools = {}
        log_path = PREFIX + "/cache-hits.jsonl"
        await environment.root_command("mkdir -p " + PREFIX + "/bin /tmp/harnesslab-download-probe")
        for tool, wrapper in [("wget", wget_wrapper), ("curl", curl_wrapper)]:
            binary = (
                await environment.root_command("command -v " + tool + " || true")
            ).stdout.strip()
            if not binary:
                continue
            await environment._sandbox.files.write(
                PREFIX + "/bin/" + tool, wrapper(PYTHON, binary, content["downloads"], log_path)
            )
            await environment.root_command("chmod 755 " + PREFIX + "/bin/" + tool)
            tools[tool] = binary
        if "wget" not in tools:
            raise ValueError("The task image must provide wget for its official download command")
        shell_path = (await environment.root_command('printf "%s" "$PATH"')).stdout.strip()
        env = {"PATH": PREFIX + "/bin:" + shell_path}
        await environment._sandbox.update_network({"allow_internet_access": False, "allow_out": []})
        for item in recipe["files"]:
            result = await environment.exec(
                "cd /tmp/harnesslab-download-probe && wget " + shlex.quote(item["url"]),
                env=env,
                timeout_sec=120,
            )
            if result.return_code:
                raise RuntimeError("Cached public release did not download offline")
        check = f"""import hashlib,json
from pathlib import Path
expected={content["files"]!r}
for name,info in expected.items():
    with (Path('/tmp/harnesslab-download-probe')/name).open('rb') as stream:
        assert hashlib.file_digest(stream,'sha256').hexdigest()==info['sha256']
print(json.dumps({{'verified_files':len(expected)}}))
"""
        record["offline_probe"] = json.loads((await environment.python_command(check)).stdout)
        await environment._sandbox.files.write(log_path, "")
        archive_code = f"""import hashlib,json,tarfile
from pathlib import Path
archive=Path('/tmp/public-downloads.tar.gz')
with tarfile.open(archive,'w:gz') as stream:stream.add({PREFIX!r},arcname={PREFIX.lstrip("/")!r})
parts=[]
with archive.open('rb') as stream:
    while data:=stream.read({PART_SIZE}):
        part=str(archive)+'.part-'+str(len(parts));Path(part).write_bytes(data);parts.append(part)
with archive.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
print(json.dumps({{'sha256':sha,'bytes':archive.stat().st_size,'parts':parts}}))
"""
        info = json.loads((await environment.python_command(archive_code, timeout=600)).stdout)
        archive = folder / "public-downloads.tar.gz"
        with archive.open("wb") as stream:
            for part in info["parts"]:
                stream.write(
                    await environment._sandbox.files.read(part, format="bytes", request_timeout=180)
                )
        with archive.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != info["sha256"]:
                raise ValueError("Transferred public release archive changed")
        record.update(
            ok=True,
            env=env,
            tools=tools,
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
        print(
            json.dumps(
                {key: record.get(key) for key in ["task", "ok", "archive", "error", "cleanup"]}
            ),
            flush=True,
        )
    return record


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
    profiles = json.loads((root / "configs/coding-public-downloads.json").read_text())
    provenance = json.loads((args.dataset / "provenance.json").read_text())
    if profiles["benchmark_revision"] != provenance["revision"]:
        raise ValueError("Public releases belong to a different task revision")
    results = [
        await prepare_one(root, args.dataset, args.run, task, profiles["tasks"][task])
        for task in args.tasks
    ]
    save_json(
        root / "artifacts/coding-public-downloads" / args.run / "summary.json",
        {"model_calls": 0, "results": results},
    )
    raise SystemExit(0 if all(row["ok"] and row["cleanup"]["verified"] for row in results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
