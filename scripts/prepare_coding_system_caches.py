"""Cache official verifier system packages against each task's original image."""

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

PREFIX = "/opt/harnesslab-verifier-system"
PART_SIZE = 16 * 1024 * 1024
REVISION = "12b7565679ce5006230b820666353673a133db93"


async def prepare_one(root: Path, dataset: Path, run: str, name: str, packages: list[str]) -> dict:
    from benchmark_next_bootstrap import prepare_tb21
    from benchmark_next_cleanup import cleanup_run
    from benchmark_next_environment import source_fingerprint
    from harbor.models.task.config import TaskConfig
    from harbor.models.trial.paths import TrialPaths

    from harnesslab.coding.native_environment import NativeStudyEnvironment

    source = dataset / "tasks" / name
    spec = TaskConfig.model_validate_toml((source / "task.toml").read_text())
    fingerprint = source_fingerprint(source / "environment", spec.environment)
    folder = root / "artifacts/coding-system-caches" / run / name
    receipt = folder / "receipt.json"
    if receipt.exists():
        saved = json.loads(receipt.read_text())
        if (
            saved["packages"] == packages
            and saved["source_fingerprint"] == fingerprint
            and saved["ok"]
            and saved["cleanup"]["verified"]
        ):
            with (root / saved["archive"]["archive"]).open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() == saved["archive"]["sha256"]:
                    return saved
        raise ValueError("Inspect previous system cache preparation before a new run")
    profile = folder / "profile.json"
    save_json(
        profile,
        {
            "tasks": {
                name: {
                    "runtime_profile": "native",
                    "source_fingerprint": fingerprint,
                    "capture_paths": ["/app"],
                    "archives": [],
                }
            }
        },
    )
    identity = run + "-" + name
    environment = NativeStudyEnvironment(
        environment_dir=source / "environment",
        environment_name=name,
        session_id=identity,
        trial_paths=TrialPaths(trial_dir=folder / "trial"),
        task_env_config=spec.environment,
        profile_file=".env.sandbox",
        image_map="configs/benchmark-images-next.json",
        sandbox_timeout_secs=1800,
        prerequisites_manifest=str(profile.relative_to(root)),
    )
    result = {
        "task": name,
        "source_fingerprint": fingerprint,
        "packages": packages,
        "ok": False,
        "model_calls": 0,
    }
    owned = set()
    try:
        await environment.start(False)
        owned.add(environment._sandbox.sandbox_id)
        result["sandbox_id"] = environment._sandbox.sandbox_id
        save_json(receipt, result)
        await prepare_tb21(root, environment)
        ca_path = "/opt/harnesslab-controller/preparation-ca.pem"
        ca_bundle = Path(certifi.where()).read_bytes()
        await environment._sandbox.files.write(ca_path, ca_bundle)
        result["preparation_ca"] = {
            "certifi_version": certifi.__version__,
            "sha256": hashlib.sha256(ca_bundle).hexdigest(),
        }
        apt = "apt-get -o Acquire::https::CaInfo=" + shlex.quote(ca_path)
        command = (
            f"mkdir -p {PREFIX}/debs/partial && {apt} update -qq && "
            f"{apt} -y --download-only -o Dir::Cache::archives={PREFIX}/debs install "
            + shlex.join(packages)
        )
        (folder / "prepare.sh").write_text(command + "\n")
        output = await environment.exec(command, user="root", timeout_sec=600)
        (folder / "prepare.stdout").write_text(output.stdout or "")
        (folder / "prepare.stderr").write_text(output.stderr or "")
        if output.return_code:
            raise RuntimeError("System package download failed; see preparation logs")
        install = (
            f"if ls {PREFIX}/debs/*.deb >/dev/null 2>&1; then "
            "DEBIAN_FRONTEND=noninteractive apt-get -y --no-download "
            f"-o Dir::Cache::archives={PREFIX}/debs install {PREFIX}/debs/*.deb; fi"
        )
        await environment._sandbox.update_network({"allow_internet_access": False, "allow_out": []})
        offline = await environment.exec(install, user="root", timeout_sec=300)
        (folder / "offline.stdout").write_text(offline.stdout or "")
        (folder / "offline.stderr").write_text(offline.stderr or "")
        if offline.return_code:
            raise RuntimeError("Cached packages could not be installed offline")
        versions = await environment.root_command(
            "dpkg-query -W -f='${Package}=${Version}\\n' " + shlex.join(packages)
        )
        result["offline_probe"] = {"return_code": offline.return_code, "versions": versions.stdout}
        code = f"""import hashlib,json,subprocess,tarfile
from pathlib import Path
prefix=Path({PREFIX!r});files={{}}
for path in sorted((prefix/'debs').glob('*.deb')):
    with path.open('rb') as stream: digest=hashlib.file_digest(stream,'sha256').hexdigest()
    files[path.name]={{'sha256':digest,'bytes':path.stat().st_size,
        'metadata':subprocess.check_output(['dpkg-deb','-f',str(path)],text=True)}}
(prefix/'files.json').write_text(json.dumps(files,sort_keys=True))
archive=Path('/tmp/verifier-system.tar.gz')
with tarfile.open(archive,'w:gz') as stream:stream.add(prefix,arcname=str(prefix).lstrip('/'))
parts=[]
with archive.open('rb') as stream:
    while data:=stream.read({PART_SIZE}):
        part=str(archive)+'.part-'+str(len(parts));Path(part).write_bytes(data);parts.append(part)
with archive.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
print(json.dumps({{'parts':parts,'files':files,'sha256':digest,'bytes':archive.stat().st_size}}))
"""
        info = json.loads((await environment.python_command(code, timeout=300)).stdout)
        archive = folder / "system.tar.gz"
        with archive.open("wb") as stream:
            for part in info["parts"]:
                stream.write(
                    await environment._sandbox.files.read(part, format="bytes", request_timeout=180)
                )
        with archive.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != info["sha256"]:
                raise ValueError("Transferred system cache checksum mismatch")
        result.update(
            ok=True,
            archive={
                "archive": str(archive.relative_to(root)),
                "sha256": info["sha256"],
                "bytes": info["bytes"],
            },
            files=info["files"],
            install_command=install,
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
                    for key in ("task", "ok", "archive", "offline_probe", "error", "cleanup")
                }
            ),
            flush=True,
        )
    return result


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--tasks", nargs="+", required=True)
    parser.add_argument("--packages", nargs="+", default=["curl"])
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,47}", args.run):
        raise ValueError("Use a short preparation run name")
    provenance = json.loads((args.dataset / "provenance.json").read_text())
    if provenance["revision"] != REVISION:
        raise ValueError("System cache source revision differs from the study")
    for name in args.tasks:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]+", name):
            raise ValueError("Use dataset task names")
        relative = "tasks/" + name + "/tests/test.sh"
        if (
            hashlib.sha256((args.dataset / relative).read_bytes()).hexdigest()
            != provenance["files"][relative]
        ):
            raise ValueError("Official verifier source changed: " + name)
    root = project_root()
    configure_runtime(root)
    os.environ.pop("BENCHMARK_NEXT_RUN", None)
    gate = asyncio.Semaphore(2)

    async def one(name):
        async with gate:
            return await prepare_one(root, args.dataset, args.run, name, args.packages)

    results = await asyncio.gather(*(one(name) for name in args.tasks))
    save_json(
        root / "artifacts/coding-system-caches" / args.run / "summary.json",
        {"model_calls": 0, "revision": REVISION, "results": results},
    )
    raise SystemExit(0 if all(row["ok"] and row["cleanup"]["verified"] for row in results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
