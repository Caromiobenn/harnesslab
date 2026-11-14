"""Cache pinned public R sources and verify a fresh installation without internet."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import shlex
import tarfile
import urllib.request
from pathlib import Path

from harnesslab.coding.config import configure_runtime, project_root, save_json

PREFIX = "/opt/harnesslab-public-r"
PART_SIZE = 16 * 1024 * 1024


def verify_package(path, package):
    with tarfile.open(path) as archive:
        description = archive.extractfile(package["name"] + "/DESCRIPTION").read().decode()
    fields = dict(re.findall(r"^(Package|Version):\s*(.+)$", description, re.MULTILINE))
    if fields != {"Package": package["name"], "Version": package["version"]}:
        raise ValueError("Public R source package differs from its declared name or version")
    return {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}


R_PROFILE = f"""local({{
  cached <- "file://{PREFIX}/repo"
  repos <- getOption("repos")
  if (is.null(repos) || any(repos == "@CRAN@"))
    repos <- c(CRAN = "https://cloud.r-project.org")
  if (Sys.getenv("HARNESSLAB_R_OFFLINE") == "1")
    options(repos = c(CRAN = cached))
  else
    options(repos = c(HarnessLab = cached, repos))
}})
"""


def installation_probe(recipe):
    lines = ["if (!requireNamespace('remotes', quietly=TRUE)) install.packages('remotes')"]
    for package in recipe["packages"]:
        name, version = json.dumps(package["name"]), json.dumps(package["version"])
        lines.extend(
            [
                f"remotes::install_version({name}, version={version}, upgrade='never')",
                f"stopifnot(as.character(packageVersion({name})) == {version})",
                f"library({name}, character.only=TRUE)",
                f"cat({name}, '=', as.character(packageVersion({name})), '\\n', sep='')",
            ]
        )
    return "; ".join(lines)


async def prepare_one(root, dataset, run, task, recipe):
    from benchmark_next_cleanup import cleanup_run
    from benchmark_next_environment import source_fingerprint
    from harbor.models.task.config import TaskConfig
    from harbor.models.trial.paths import TrialPaths

    from harnesslab.coding.native_environment import NativeStudyEnvironment

    source = dataset / "tasks" / task
    provenance = json.loads((dataset / "provenance.json").read_text())
    spec = TaskConfig.model_validate_toml((source / "task.toml").read_text())
    fingerprint = source_fingerprint(source / "environment", spec.environment)
    folder = root / "artifacts/coding-actor-r" / run / task
    if folder.exists():
        raise ValueError("Inspect the existing R cache preparation before selecting a new run")
    folder.mkdir(parents=True)
    record = {
        "task": task,
        "recipe": recipe,
        "benchmark_revision": provenance["revision"],
        "source_fingerprint": fingerprint,
        "model_calls": 0,
        "ok": False,
    }
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
    identity = run + "-r-" + task
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
    owned = set()
    try:
        packages = {}
        for package in recipe["packages"]:
            name = package["name"] + "_" + package["version"] + ".tar.gz"
            if Path(name).name != name:
                raise ValueError("Use a public R package name and version")
            path = folder / name
            with urllib.request.urlopen(package["url"], timeout=90) as response:
                path.write_bytes(response.read())
            packages[name] = {**verify_package(path, package), "url": package["url"]}
        record["packages"] = packages
        await environment.start(False)
        owned.add(environment._sandbox.sandbox_id)
        record["sandbox_id"] = environment._sandbox.sandbox_id
        save_json(folder / "receipt.json", record)
        await environment.root_command(
            f"mkdir -p {PREFIX}/repo/src/contrib /tmp/harnesslab-r-probe"
        )
        for name in packages:
            await environment._sandbox.files.write(
                PREFIX + "/repo/src/contrib/" + name, (folder / name).read_bytes()
            )
        await environment._sandbox.files.write(PREFIX + "/profile.R", R_PROFILE)
        build = (
            "tools::write_PACKAGES(" + json.dumps(PREFIX + "/repo/src/contrib") + ", type='source')"
        )
        await environment.root_command("Rscript -e " + shlex.quote(build))
        env = {"R_PROFILE_USER": PREFIX + "/profile.R"}
        offline_env = {**env, "HARNESSLAB_R_OFFLINE": "1", "R_LIBS_USER": "/tmp/harnesslab-r-probe"}
        await environment._sandbox.update_network({"allow_internet_access": False, "allow_out": []})
        command = "Rscript -e " + shlex.quote(installation_probe(recipe))
        (folder / "offline.sh").write_text(command + "\n")
        probe = await environment.exec(command, env=offline_env, timeout_sec=1200)
        (folder / "offline.stdout").write_text(probe.stdout or "")
        (folder / "offline.stderr").write_text(probe.stderr or "")
        if probe.return_code:
            raise RuntimeError("Public R sources did not install and load offline")
        record["offline_probe"] = {"return_code": 0, "stdout": probe.stdout[-1200:]}
        archive_code = f"""import hashlib,json,tarfile
from pathlib import Path
prefix=Path({PREFIX!r});archive=Path('/tmp/actor-r.tar.gz')
with tarfile.open(archive,'w:gz') as stream:stream.add(prefix,arcname=str(prefix).lstrip('/'))
parts=[]
with archive.open('rb') as stream:
    while data:=stream.read({PART_SIZE}):
        part=str(archive)+'.part-'+str(len(parts));Path(part).write_bytes(data);parts.append(part)
with archive.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
print(json.dumps({{'sha256':digest,'bytes':archive.stat().st_size,'parts':parts}}))
"""
        info = json.loads((await environment.python_command(archive_code, timeout=300)).stdout)
        archive = folder / "actor-r.tar.gz"
        with archive.open("wb") as stream:
            for part in info["parts"]:
                stream.write(
                    await environment._sandbox.files.read(part, format="bytes", request_timeout=180)
                )
        if hashlib.sha256(archive.read_bytes()).hexdigest() != info["sha256"]:
            raise ValueError("Transferred R source archive changed")
        record.update(
            ok=True,
            env=env,
            offline_env={"HARNESSLAB_R_OFFLINE": "1"},
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
    profiles = json.loads((root / "configs/coding-actor-r.json").read_text())
    provenance = json.loads((args.dataset / "provenance.json").read_text())
    if profiles["benchmark_revision"] != provenance["revision"]:
        raise ValueError("R cache recipe belongs to a different task revision")
    results = [
        await prepare_one(root, args.dataset, args.run, task, profiles["tasks"][task])
        for task in args.tasks
    ]
    save_json(
        root / "artifacts/coding-actor-r" / args.run / "summary.json",
        {"model_calls": 0, "results": results},
    )
    raise SystemExit(0 if all(row["ok"] and row["cleanup"]["verified"] for row in results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
