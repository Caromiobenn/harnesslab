"""Prepare pinned public datasets for the verifier after actor submission."""

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

from harnesslab.coding.config import configure_runtime, load_config, project_root, save_json
from harnesslab.coding.native_controls import public_cache, task_prerequisites
from harnesslab.coding.runner import task_plan

PREFIX = "/opt/harnesslab-verifier-datasets"
PART_SIZE = 16 * 1024 * 1024


def dataset_code(recipe: dict, online: bool) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", recipe["revision"]):
        raise ValueError("A verifier dataset needs a fixed repository revision")
    return f"""import hashlib,json
from pathlib import Path
from datasets import load_dataset
from huggingface_hub import HfApi,hf_hub_download
recipe={recipe!r};prefix=Path({PREFIX!r});prefix.mkdir(parents=True,exist_ok=True)
if {online!r}:
    assert HfApi().dataset_info(recipe['repository']).sha==recipe['revision']
    for filename,expected in recipe['sha256'].items():
        path=Path(hf_hub_download(recipe['repository'],filename,repo_type='dataset',
                                 revision=recipe['revision']))
        with path.open('rb') as stream:actual=hashlib.file_digest(stream,'sha256').hexdigest()
        assert actual==expected,(filename,actual)
    pinned=load_dataset(recipe['repository'],data_files=recipe['data_files'],
                        revision=recipe['revision'],split=recipe['split'])
data=load_dataset(recipe['repository'],data_files=recipe['data_files'],split=recipe['split'])
record={{'rows':len(data),'columns':data.column_names,'fingerprint':data._fingerprint,
         'repository':recipe['repository'],'revision':recipe['revision']}}
if {online!r}:
    assert len(pinned)==len(data) and pinned._fingerprint==data._fingerprint
    (prefix/'download.json').write_text(json.dumps(record))
else:
    assert record==json.loads((prefix/'download.json').read_text())
(prefix/({"download" if online else "offline"!r}+'-probe.json')).write_text(json.dumps(record))
print('DATASET_PROBE',json.dumps(record))
"""


async def prepare_one(root: Path, dataset: Path, run: str, task: str, recipe: dict, ledger: dict):
    from benchmark_next_cleanup import cleanup_run
    from harbor.models.task.config import TaskConfig
    from harbor.models.trial.paths import TrialPaths

    from harnesslab.coding.native_environment import CONTROL, PYTHON, NativeStudyEnvironment
    from harnesslab.coding.verifier_cache import prepare_verifier

    config = load_config(root, Path("configs/coding-tb21-full.json"))
    row = task_plan(root, config, task)
    source = dataset / "tasks" / task
    if source.resolve() != Path(row["path"]).resolve():
        raise ValueError("Dataset preparation source differs from the task lock")
    folder = root / "artifacts/coding-verifier-datasets" / run / task
    if folder.exists():
        raise ValueError("Inspect the previous dataset preparation before choosing another run")
    spec = TaskConfig.model_validate_toml((source / "task.toml").read_text())
    profiles = json.loads((root / "configs/coding-native-control-profiles.json").read_text())
    entry = task_prerequisites(
        root, row, ["/app"], ledger, profiles["tasks"][task].get("verifier_env")
    )
    choices = [
        entry for entry in ledger["families"]["shared_python"].values() if task in entry["tasks"]
    ]
    if len(choices) != 1:
        raise ValueError("Dataset preparation needs the accepted official uvx recipe")
    python_cache = public_cache(root, choices[0])
    profile = folder / "profile.json"
    save_json(profile, {"tasks": {task: entry}})
    identity = run + "-verifierdata-" + task
    environment = NativeStudyEnvironment(
        environment_dir=source / "environment",
        environment_name=task,
        session_id=identity,
        trial_paths=TrialPaths(trial_dir=folder / "trial"),
        task_env_config=spec.environment,
        profile_file=".env.sandbox",
        image_map="configs/benchmark-images-next.json",
        sandbox_timeout_secs=7200,
        prerequisites_manifest=str(profile.relative_to(root)),
    )
    env = {
        "HF_HOME": PREFIX,
        "HF_HUB_DISABLE_XET": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "HF_HUB_ETAG_TIMEOUT": "30",
        "HF_HUB_DOWNLOAD_TIMEOUT": "180",
    }
    offline_env = {"HF_HUB_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1"}
    record = {
        "task": task,
        "recipe": recipe,
        "source_fingerprint": row["source_fingerprint"],
        "benchmark_revision": config.revision,
        "model_calls": 0,
        "ok": False,
        "test_script_sha256": entry["verifier"]["test_script_sha256"],
    }
    owned = set()
    try:
        await environment.start(False)
        owned.add(environment._sandbox.sandbox_id)
        record["sandbox_id"] = environment._sandbox.sandbox_id
        save_json(folder / "receipt.json", record)
        verifier_env = await prepare_verifier(environment, entry["verifier"], CONTROL, PYTHON)
        ca = CONTROL + "/verifier-dataset-ca.pem"
        await environment._sandbox.files.write(ca, Path(certifi.where()).read_bytes())
        for phase, online in [("download", True), ("offline", False)]:
            await environment._sandbox.update_network(
                {"allow_internet_access": online, "allow_out": []}
            )
            code = dataset_code(recipe, online)
            script = "def test_dataset_cache():\n    exec(" + repr(code) + ")\n"
            (folder / (phase + ".py")).write_text(script)
            target = "/tmp/verifier-dataset-" + phase + ".py"
            await environment._sandbox.files.write(target, script)
            args = [*python_cache["recipe"]["args"], "pytest", "-q", "-s", target]
            current_env = {
                **verifier_env,
                **env,
                "REQUESTS_CA_BUNDLE": ca,
                "SSL_CERT_FILE": ca,
                **({} if online else offline_env),
            }
            output = await environment.exec(
                shlex.join(args), env=current_env, timeout_sec=2400 if online else 300
            )
            (folder / (phase + ".stdout")).write_text(output.stdout or "")
            (folder / (phase + ".stderr")).write_text(output.stderr or "")
            if output.return_code:
                raise RuntimeError("Verifier dataset " + phase + " probe failed")
            record[phase] = json.loads(
                await environment._sandbox.files.read(PREFIX + "/" + phase + "-probe.json")
            )
            save_json(folder / "receipt.json", record)
        code = f"""import hashlib,json,tarfile
from pathlib import Path
prefix=Path({PREFIX!r});files={{}}
for path in prefix.rglob('*'):
    if path.is_file() and not path.is_symlink():
        with path.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
        files[str(path.relative_to(prefix))]={{'sha256':sha,'bytes':path.stat().st_size}}
archive=Path('/tmp/verifier-datasets.tar.gz')
with tarfile.open(archive,'w:gz') as stream:stream.add(prefix,arcname=str(prefix).lstrip('/'))
parts=[]
with archive.open('rb') as stream:
    while data:=stream.read({PART_SIZE}):
        part=str(archive)+'.part-'+str(len(parts));Path(part).write_bytes(data);parts.append(part)
with archive.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
print(json.dumps({{'sha256':sha,'bytes':archive.stat().st_size,'parts':parts,'files':files}}))
"""
        info = json.loads((await environment.python_command(code, timeout=1200)).stdout)
        archive = folder / "verifier-datasets.tar.gz"
        with archive.open("wb") as stream:
            for part in info["parts"]:
                stream.write(
                    await environment._sandbox.files.read(part, format="bytes", request_timeout=180)
                )
        with archive.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != info["sha256"]:
                raise ValueError("Transferred verifier dataset archive changed")
        record.update(
            ok=True,
            files=info["files"],
            python_downloads={},
            verifier_env={**env, **offline_env},
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
            json.dumps({k: record.get(k) for k in ["task", "ok", "archive", "error", "cleanup"]}),
            flush=True,
        )
    return record


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--cache-ledger", type=Path, required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--tasks", nargs="+", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,47}", args.run):
        raise ValueError("Use a short dataset preparation run name")
    root = project_root()
    configure_runtime(root)
    os.environ.pop("BENCHMARK_NEXT_RUN", None)
    profiles = json.loads((root / "configs/coding-verifier-datasets.json").read_text())
    provenance = json.loads((args.dataset / "provenance.json").read_text())
    ledger = json.loads(args.cache_ledger.read_text())
    if (
        profiles["benchmark_revision"] != provenance["revision"]
        or ledger["benchmark_revision"] != provenance["revision"]
    ):
        raise ValueError("Verifier dataset profile belongs to another benchmark revision")
    rows = [
        await prepare_one(root, args.dataset, args.run, task, profiles["tasks"][task], ledger)
        for task in args.tasks
    ]
    save_json(
        root / "artifacts/coding-verifier-datasets" / args.run / "summary.json",
        {"model_calls": 0, "results": rows},
    )
    raise SystemExit(0 if all(row["ok"] and row["cleanup"]["verified"] for row in rows) else 1)


if __name__ == "__main__":
    asyncio.run(main())
