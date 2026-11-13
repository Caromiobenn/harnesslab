"""Import only the pinned six tasks and the existing Hong Kong environment adapter."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from harnesslab.coding.config import load_config, save_json

MODULES = (
    "benchmark_next_environment.py",
    "benchmark_next_cpu.py",
    "benchmark_next_command.py",
    "benchmark_next_cleanup.py",
    "sandbox_profile.py",
    "benchmark_next_bootstrap.py",
    "agent_artifacts.py",
)

PATHS_MODULE = '''"""HarnessLab-local paths for the reused Hong Kong adapter."""
import os
from pathlib import Path


def project_root(value=None):
    return Path(value or os.environ["HARNESSLAB_ROOT"]).resolve()


def inside(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Path is outside HarnessLab")
    return path
'''


def import_infra(source: Path, root: Path) -> dict:
    config = load_config(root)
    vendor = root / "vendor/hongkong"
    vendor.mkdir(parents=True, exist_ok=True)
    sources = {}
    for name in MODULES:
        origin = source / "scripts" / name
        content = origin.read_bytes()
        sources[f"scripts/{name}"] = hashlib.sha256(content).hexdigest()
        (vendor / name).write_bytes(content)
    (vendor / "project_paths.py").write_text(PATHS_MODULE)
    for name in ("benchmark-images-next.json", "benchmark-runtime-next.json"):
        content = (source / "configs" / name).read_bytes()
        sources[f"configs/{name}"] = hashlib.sha256(content).hexdigest()
        (root / "configs" / name).write_bytes(content)
    dataset = source / "cache/benchmark-next" / f"{config.benchmark}-{config.revision[:12]}"
    provenance = json.loads((dataset / "provenance.json").read_text())
    if provenance["revision"] != config.revision:
        raise ValueError("Source dataset revision differs from experiment")
    target = root / "artifacts/datasets" / config.benchmark
    hashes = {}
    for task in config.tasks:
        for origin in (dataset / "tasks" / task).rglob("*"):
            if origin.is_symlink():
                raise ValueError("Unexpected task symlink")
            if not origin.is_file():
                continue
            relative = origin.relative_to(dataset).as_posix()
            digest = hashlib.sha256(origin.read_bytes()).hexdigest()
            if provenance["files"].get(relative) != digest:
                raise ValueError(f"Source task changed: {relative}")
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origin, destination)
            hashes[relative] = digest
    save_json(
        root / "configs/coding-tasks.lock.json",
        {
            "repository": "https://github.com/harbor-framework/terminal-bench-2-1",
            "revision": config.revision,
            "tasks": config.tasks,
            "files": hashes,
        },
    )
    # The adapter may prepare these exact official verifier runtime versions.
    manifest = source / "manifests/bootstrap-artifacts.json"
    if manifest.exists():
        (root / "manifests").mkdir(exist_ok=True)
        shutil.copy2(manifest, root / "manifests/bootstrap-artifacts.json")
        for name in ("uv-x86_64-unknown-linux-gnu.tar.gz", "python313.tar.gz"):
            destination = root / "cache/bootstrap" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / "cache/bootstrap" / name, destination)
    receipt = {
        "source_project": str(source),
        "source_files": sources,
        "builder_repository": "https://github.com/Caromiobenn/benchmark-sandbox-builder",
        "workflow": ".github/workflows/benchmark.yml",
        "adaptation": (
            "project_paths.py redirects reads/writes to HarnessLab; other modules unchanged"
        ),
        "task_count": len(config.tasks),
        "task_file_count": len(hashes),
    }
    save_json(root / "vendor/hongkong/provenance.json", receipt)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    receipt = import_infra(args.source.resolve(), Path(__file__).resolve().parents[1])
    print(json.dumps({"tasks_imported": receipt["task_count"]}))
