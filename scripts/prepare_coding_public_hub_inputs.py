"""Pin public model/data inputs and check ordinary library loading without internet."""

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

PREFIX = "/opt/harnesslab-public-hub"
PART_SIZE = 16 * 1024 * 1024


def download_code(recipe: dict) -> str:
    for repo in recipe["repositories"]:
        if not re.fullmatch(r"[0-9a-f]{40}", repo["revision"]):
            raise ValueError("Public inputs require full commit revisions")
    return f"""import json,os
from pathlib import Path
from huggingface_hub import snapshot_download
recipes={recipe["repositories"]!r}
root=Path({PREFIX!r}); records=[]
for repo in recipes:
    snapshot=Path(snapshot_download(repo['repo_id'],repo_type=repo['repo_type'],
        revision=repo['revision'],allow_patterns=repo['files'],max_workers=2))
    assert snapshot.name==repo['revision']
    missing=[name for name in repo['files'] if not (snapshot/name).is_file()]
    assert not missing,missing
    cache=snapshot.parent.parent
    (cache/'refs').mkdir(exist_ok=True)
    (cache/'refs/main').write_text(repo['revision'])
    for alias in repo.get('aliases',[]):
        target=cache.parent/(repo['repo_type']+'s--'+alias.replace('/','--'))
        if not target.exists():target.symlink_to(cache.name,target_is_directory=True)
    if repo['repo_type']=='dataset':
        from datasets import load_dataset
        for config in repo['configs']:
            data=load_dataset(repo['repo_id'],config,revision=repo['revision'],split='train')
            records.append({{'repository':repo['repo_id'],'configuration':config,'rows':len(data)}})
    records.append({{'repository':repo['repo_id'],'revision':repo['revision'],'snapshot':str(snapshot)}})
print(json.dumps(records))
"""


def probe_code(recipe: dict) -> str:
    model = next(repo for repo in recipe["repositories"] if repo["repo_type"] == "model")
    names = [model["repo_id"], *model.get("aliases", [])]
    code = f"""import json
from transformers import AutoTokenizer
records=[]
for name in {names!r}:
    tokenizer=AutoTokenizer.from_pretrained(name)
    records.append({{'repository':name,'tokenizer_class':type(tokenizer).__name__}})
"""
    if recipe["kind"] == "sentiment_model":
        code += f"""from transformers import AutoModelForSequenceClassification
for name in {names!r}:
    model=AutoModelForSequenceClassification.from_pretrained(name)
    records.append({{'repository':name,'model_class':type(model).__name__}})
"""
    elif recipe["kind"] == "dataset_tokenizer":
        dataset = next(repo for repo in recipe["repositories"] if repo["repo_type"] == "dataset")
        code += f"""from datasets import load_dataset
for config in {dataset["configs"]!r}:
    data=load_dataset({dataset["repo_id"]!r},config,split='train')
    records.append({{'configuration':config,'rows':len(data)}})
"""
    elif recipe["kind"] == "mteb_embedding":
        code += f"""import mteb
from importlib.metadata import version
assert version('mteb')=={recipe["mteb_version"]!r}
model=mteb.get_model({model["repo_id"]!r},revision={model["revision"]!r})
embedding=model.encode(['public dependency cache probe'],task_name='SciFact',
    prompt_type=mteb.encoder_interface.PromptType.query)
assert len(embedding.shape)==2 and embedding.shape[0]==1
records.append({{'repository':{model["repo_id"]!r},'revision':{model["revision"]!r},
    'mteb_version':version('mteb'),'probe_shape':list(embedding.shape)}})
"""
    else:
        raise ValueError("Unknown public input loading probe")
    return code + "print(json.dumps(records))\n"


async def prepare_one(root: Path, dataset: Path, run: str, task: str, recipe: dict, ledger: dict):
    from benchmark_next_cleanup import cleanup_run
    from benchmark_next_environment import source_fingerprint
    from harbor.models.task.config import TaskConfig
    from harbor.models.trial.paths import TrialPaths

    from harnesslab.coding.native_environment import CONTROL, NativeStudyEnvironment

    source = dataset / "tasks" / task
    provenance = json.loads((dataset / "provenance.json").read_text())
    spec = TaskConfig.model_validate_toml((source / "task.toml").read_text())
    fingerprint = source_fingerprint(source / "environment", spec.environment)
    folder = root / "artifacts/coding-public-hub-inputs" / run / task
    if folder.exists():
        raise ValueError("Inspect previous public input preparation before choosing a new run")
    entry = {
        "runtime_profile": "native",
        "source_fingerprint": fingerprint,
        "capture_paths": ["/app"],
        "archives": [],
        "env": {},
    }
    actor = None
    if task in ledger["families"].get("actor_python", {}):
        actor = public_cache(root, ledger["families"]["actor_python"][task])
        if actor["source_fingerprint"] != fingerprint:
            raise ValueError("Public installer image differs from task image")
        entry.update(archives=[actor["archive"]], env=actor["env"])
    profile = folder / "profile.json"
    save_json(profile, {"tasks": {task: entry}})
    identity = run + "-hub-" + task
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
    env = {
        "HF_HOME": PREFIX,
        "HF_HUB_ETAG_TIMEOUT": "1",
        "HF_HUB_DOWNLOAD_TIMEOUT": "60",
        "HF_HUB_DISABLE_XET": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
    }
    offline_env = {"HF_HUB_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1"}
    if actor:
        offline_env["PIP_NO_INDEX"] = "1"
    result = {
        "task": task,
        "recipe": recipe,
        "source_fingerprint": fingerprint,
        "benchmark_revision": provenance["revision"],
        "instruction_sha256": hashlib.sha256((source / "instruction.md").read_bytes()).hexdigest(),
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
        if actor:
            # A fresh instance verifies that cached installers, not pip's download cache,
            # suffice. Installed packages remain in this disposable preparation only.
            await environment._sandbox.update_network(
                {"allow_internet_access": False, "allow_out": []}
            )
            install = await environment.exec(
                shlex.quote(python) + " -m pip install " + shlex.join(actor["recipe"]["packages"]),
                env={**actor["env"], "PIP_NO_INDEX": "1"},
                timeout_sec=300,
            )
            (folder / "install.stdout").write_text(install.stdout or "")
            (folder / "install.stderr").write_text(install.stderr or "")
            if install.return_code:
                raise RuntimeError("Fresh-instance public package installation failed")
            await environment._sandbox.update_network(
                {"allow_internet_access": True, "allow_out": []}
            )
        ca_path = CONTROL + "/public-ca.pem"
        await environment._sandbox.files.write(ca_path, Path(certifi.where()).read_bytes())
        online_env = {**env, "REQUESTS_CA_BUNDLE": ca_path, "SSL_CERT_FILE": ca_path}
        for phase, code in (("download", download_code(recipe)), ("offline", probe_code(recipe))):
            if phase == "offline":
                await environment._sandbox.update_network(
                    {"allow_internet_access": False, "allow_out": []}
                )
            (folder / (phase + ".py")).write_text(code)
            output = await environment.exec(
                shlex.quote(python) + " -c " + shlex.quote(code),
                env={**online_env, **(offline_env if phase == "offline" else {})},
                timeout_sec=1800 if phase == "download" else 300,
            )
            (folder / (phase + ".stdout")).write_text(output.stdout or "")
            (folder / (phase + ".stderr")).write_text(output.stderr or "")
            if output.return_code:
                raise RuntimeError("Public input " + phase + " probe failed")
            result[phase] = json.loads(output.stdout.strip().splitlines()[-1])
            save_json(folder / "receipt.json", result)
        archive_code = f"""import hashlib,json,tarfile
from pathlib import Path
prefix=Path({PREFIX!r});files={{}}
for path in prefix.rglob('*'):
    if path.is_file() and not path.is_symlink():
        with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        files[str(path.relative_to(prefix))]={{'sha256':digest,'bytes':path.stat().st_size}}
archive=Path('/tmp/public-hub-inputs.tar.gz')
with tarfile.open(archive,'w:gz') as stream:stream.add(prefix,arcname=str(prefix).lstrip('/'))
parts=[]
with archive.open('rb') as stream:
    while data:=stream.read({PART_SIZE}):
        part=str(archive)+'.part-'+str(len(parts));Path(part).write_bytes(data);parts.append(part)
with archive.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
print(json.dumps({{'sha256':digest,'bytes':archive.stat().st_size,'parts':parts,'files':files}}))
"""
        info = json.loads((await environment.python_command(archive_code, timeout=600)).stdout)
        archive = folder / "public-hub-inputs.tar.gz"
        with archive.open("wb") as stream:
            for part in info["parts"]:
                stream.write(
                    await environment._sandbox.files.read(part, format="bytes", request_timeout=180)
                )
        with archive.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != info["sha256"]:
                raise ValueError("Transferred public input archive changed")
        result.update(
            ok=True,
            env=env,
            offline_env=offline_env,
            files=info["files"],
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
    parser.add_argument("--cache-ledger", type=Path, required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--tasks", nargs="+", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,47}", args.run):
        raise ValueError("Use a short public input preparation run name")
    root = project_root()
    configure_runtime(root)
    os.environ.pop("BENCHMARK_NEXT_RUN", None)
    profiles = json.loads((root / "configs/coding-public-hub-inputs.json").read_text())
    ledger = json.loads(args.cache_ledger.read_text())
    provenance = json.loads((args.dataset / "provenance.json").read_text())
    if (
        profiles["benchmark_revision"] != provenance["revision"]
        or ledger["benchmark_revision"] != provenance["revision"]
    ):
        raise ValueError("Public input profiles belong to a different task revision")
    gate = asyncio.Semaphore(2)

    async def one(task):
        async with gate:
            return await prepare_one(
                root, args.dataset, args.run, task, profiles["tasks"][task], ledger
            )

    rows = await asyncio.gather(*(one(task) for task in args.tasks))
    save_json(
        root / "artifacts/coding-public-hub-inputs" / args.run / "summary.json",
        {"model_calls": 0, "results": rows},
    )
    raise SystemExit(0 if all(row["ok"] and row["cleanup"]["verified"] for row in rows) else 1)


if __name__ == "__main__":
    asyncio.run(main())
