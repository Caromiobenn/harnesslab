"""Prepare public dependencies and untouched source snapshots, without solving tasks.

Run once on the CPU controller. Every artifact is built in a fresh task sandbox;
the resulting archives are shared by the online and offline experiment arms.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shlex
from pathlib import Path
from time import monotonic

from harnesslab.coding.config import configure_runtime, load_config, project_root, save_json

PREFIX = "/opt/harnesslab-prerequisites"

APT = {
    "compile-compcert": (
        "opam build-essential unzip rsync git ca-certificates curl m4 "
        "pkg-config libgmp-dev libzstd-dev python3 binutils"
    ),
    "build-cython-ext": "curl binutils",
    "cancel-async-tasks": "curl binutils",
    "db-wal-recovery": "curl binutils",
    "raman-fitting": "curl binutils",
    "regex-log": "python3 curl binutils",
}
PYTHON = {
    "build-cython-ext": (
        "numpy==2.3.0 setuptools==80.9.0 cython==3.1.3 networkx planarity==0.6 "
        "peewee vispy sympy appdirs requests tqdm scipy matplotlib "
        "pytest==8.4.1 pytest-json-ctrf==0.3.5"
    ),
    "raman-fitting": "scipy==1.16.0 numpy==2.3.1 pytest==8.4.1 pytest-json-ctrf==0.3.5",
}
SOURCES = {
    "compile-compcert": ("https://github.com/AbsInt/CompCert.git", "v3.13.1", "CompCert"),
    "build-cython-ext": ("https://github.com/SPOCKnots/pyknotid.git", "0.5.3", "pyknotid"),
}


def preparation_script(task: str) -> str:
    script = f"""set -eu
export DEBIAN_FRONTEND=noninteractive
mkdir -p {PREFIX}/debs {PREFIX}/wheels {PREFIX}/sources
apt-get update
apt-get -y --download-only -o Dir::Cache::archives={PREFIX}/debs install {APT[task]}
cp -a {PREFIX}/debs /tmp/harnesslab-preserved-debs
apt-get -y -o Dir::Cache::archives={PREFIX}/debs install {APT[task]}
cp /tmp/harnesslab-preserved-debs/*.deb {PREFIX}/debs/ 2>/dev/null || true
dpkg-query -W -f='${{Package}}=${{Version}}\\n' > {PREFIX}/dpkg-versions.txt
"""
    if task in PYTHON:
        script += f"python -m pip wheel --wheel-dir {PREFIX}/wheels {PYTHON[task]}\n"
    if task == "compile-compcert":
        script += f"""export OPAMROOT={PREFIX}/opam
export OPAMYES=1 OPAMCOLOR=never OPAMJOBS=1
opam init --bare --disable-sandboxing -a
opam switch create toolchain ocaml-base-compiler.4.14.2 -y
eval "$(opam env --switch=toolchain)"
opam install -y -j1 coq.8.16.1 menhir.20230608
opam list --installed --columns=name,version > {PREFIX}/opam-versions.txt
"""
    if task in SOURCES:
        url, tag, name = SOURCES[task]
        script += f"""git clone --depth 1 --branch {shlex.quote(tag)} \\
  {shlex.quote(url)} {PREFIX}/sources/{name}
git -C {PREFIX}/sources/{name} rev-parse HEAD > {PREFIX}/{name}.upstream-commit
"""
    # Only public dependency/source state enters the archive. No solve.sh is run.
    script += f"""python3 - <<'PY'
import hashlib,json,os,shutil,subprocess
from pathlib import Path
prefix=Path('{PREFIX}')
for repository in (prefix/'sources').iterdir():
    if not repository.is_dir(): continue
    shutil.rmtree(repository/'.git')
    files={{p.relative_to(repository).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
           for p in repository.rglob('*') if p.is_file()}}
    (prefix/(repository.name+'.source-files.json')).write_text(json.dumps(files,sort_keys=True))
for folder in (prefix/'opam/download-cache',prefix/'opam/toolchain/.opam-switch/build',
               prefix/'opam/repo'):
    if folder.exists(): shutil.rmtree(folder)
for parent,dirs,files in os.walk(prefix,topdown=True):
    for name in list(dirs):
        path=Path(parent)/name
        if name in ('__pycache__','.git') and not path.is_symlink():
            shutil.rmtree(path);dirs.remove(name)
PY
tar -C / -czf /tmp/harnesslab-prerequisites.tar.gz opt/harnesslab-prerequisites
sha256sum /tmp/harnesslab-prerequisites.tar.gz
"""
    return script


async def prepare_one(root: Path, task: str, run: str) -> dict:
    from benchmark_next_cleanup import cleanup_run
    from benchmark_next_environment import BenchmarkAliyunEnvironment
    from harbor.models.task.config import EnvironmentConfig
    from harbor.models.trial.paths import TrialPaths

    from harnesslab.coding.runner import task_plan

    config = load_config(root)
    row = task_plan(root, config, task)
    folder = root / "artifacts/coding-prerequisites" / run / task
    folder.mkdir(parents=True, exist_ok=True)
    receipt = folder / "receipt.json"
    if receipt.exists():
        saved = json.loads(receipt.read_text())
        if saved.get("ok") and saved.get("cleanup_verified"):
            return saved
        raise ValueError("Inspect incomplete preparation before using a new run name")
    script = preparation_script(task)
    (folder / "prepare.sh").write_text(script)
    environment = BenchmarkAliyunEnvironment(
        environment_dir=Path(row["path"]) / "environment",
        environment_name=task,
        session_id=run + "-" + task,
        trial_paths=TrialPaths(trial_dir=folder / "trial"),
        task_env_config=EnvironmentConfig.model_validate(row["environment"]),
        profile_file=".env.sandbox",
        sandbox_timeout_secs=5400,
    )
    result = {
        "task": task,
        "source_fingerprint": row["source_fingerprint"],
        "template_id": row["template_id"],
        "script_sha256": hashlib.sha256(script.encode()).hexdigest(),
        "public_sources": SOURCES.get(task),
        "ok": False,
    }
    owned = set()
    try:
        await environment.start(force_build=False)
        owned.add(environment._sandbox.sandbox_id)
        result["sandbox_id"] = environment._sandbox.sandbox_id
        save_json(receipt, result)
        await environment.upload_file(folder / "prepare.sh", "/tmp/harnesslab-prepare.sh")
        background = "bash /tmp/harnesslab-prepare.sh; echo $? > /tmp/harnesslab-prepare.exit"
        output = await environment.exec(
            "nohup bash -c "
            + shlex.quote(background)
            + " > /tmp/harnesslab-prepare.log 2>&1 < /dev/null &",
            timeout_sec=30,
        )
        if output.return_code:
            raise RuntimeError("Could not start dependency preparation")
        started = monotonic()
        while monotonic() - started < 4800:
            if await environment._sandbox.files.exists("/tmp/harnesslab-prepare.exit"):
                break
            await asyncio.sleep(10)
        else:
            raise TimeoutError("Dependency preparation exceeded 4800 seconds")
        result["exit_code"] = int(
            await environment._sandbox.files.read("/tmp/harnesslab-prepare.exit")
        )
        await environment.download_file("/tmp/harnesslab-prepare.log", folder / "prepare.log")
        if result["exit_code"]:
            raise RuntimeError("Public dependency preparation failed; see prepare.log")
        archive = folder / "prerequisites.tar.gz"
        remote = "/tmp/harnesslab-prerequisites.tar.gz"
        info = await environment.exec(
            f"stat -c %s {remote}; sha256sum {remote}; "
            f"split -b 16777216 -d -a 4 {remote} {remote}.part-",
            timeout_sec=120,
        )
        if info.return_code:
            raise RuntimeError("Could not split the public prerequisite archive")
        size, digest = info.stdout.splitlines()[:2]
        expected = digest.split()[0]
        parts = (int(size) + 16777215) // 16777216
        partial = archive.with_suffix(".partial")
        with partial.open("wb") as stream:
            for index in range(parts):
                stream.write(
                    await environment._sandbox.files.read(
                        f"{remote}.part-{index:04d}", format="bytes", request_timeout=180
                    )
                )
                print(
                    json.dumps({"task": task, "downloaded_parts": index + 1, "total_parts": parts}),
                    flush=True,
                )
        with partial.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if partial.stat().st_size != int(size) or actual != expected:
            raise ValueError("Transferred prerequisite archive does not match its source")
        partial.replace(archive)
        result.update(
            archive=str(archive.relative_to(root)),
            bytes=archive.stat().st_size,
            sha256=actual,
            transfer_parts=parts,
            ok=True,
        )
        print(json.dumps({"prepared": task, "bytes": result["bytes"]}), flush=True)
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if environment._sandbox:
            owned.add(environment._sandbox.sandbox_id)
            try:
                await environment.stop(delete=True)
            except Exception as exc:
                result["stop_error"] = type(exc).__name__
        cleanup = await asyncio.to_thread(
            cleanup_run, root, run + "-" + task, profile_file=".env.sandbox", expected_ids=owned
        )
        result["cleanup_verified"] = cleanup["verified"]
        save_json(receipt, result)
    return result


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    parser.add_argument("--tasks", nargs="+", choices=list(APT), default=list(APT))
    args = parser.parse_args()
    root = project_root()
    configure_runtime(root)
    # The reused adapter falls back to each environment's unique session_id.
    # A process-wide run label would let one concurrent cleanup match another task.
    os.environ.pop("BENCHMARK_NEXT_RUN", None)
    gate = asyncio.Semaphore(2)

    async def selected(task):
        async with gate:
            return await prepare_one(root, task, args.run)

    results = await asyncio.gather(*(selected(task) for task in args.tasks))
    save_json(root / "artifacts/coding-prerequisites" / args.run / "summary.json", results)
    print(json.dumps(results, indent=2))
    raise SystemExit(0 if all(row["ok"] and row["cleanup_verified"] for row in results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
