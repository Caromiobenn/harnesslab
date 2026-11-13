"""Download and pin external official-test data for verifier-only use."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tarfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

from harnesslab.coding.config import configure_runtime, project_root, save_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--tasks", nargs="+", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,47}", args.run):
        raise ValueError("Use a short verifier-input preparation run name")
    root = project_root()
    configure_runtime(root)
    from benchmark_next_environment import source_fingerprint
    from harbor.models.task.config import TaskConfig

    dataset = args.dataset
    provenance = json.loads((dataset / "provenance.json").read_text())
    profiles = json.loads((root / "configs/coding-verifier-inputs.json").read_text())
    if provenance["revision"] != profiles["benchmark_revision"]:
        raise ValueError("Verifier inputs belong to a different task revision")
    for task in args.tasks:
        recipe = profiles["tasks"][task]
        source = dataset / "tasks" / task
        spec = TaskConfig.model_validate_toml((source / "task.toml").read_text())
        folder = root / "artifacts/coding-verifier-inputs" / args.run / task
        if folder.exists():
            raise ValueError("Inspect the existing preparation before choosing a new run")
        folder.mkdir(parents=True)
        record = {
            "task": task,
            "ok": False,
            "model_calls": 0,
            "benchmark_revision": provenance["revision"],
            "source_fingerprint": source_fingerprint(source / "environment", spec.environment),
            "test_script_sha256": hashlib.sha256(
                (source / "tests/test.sh").read_bytes()
            ).hexdigest(),
            "test_sources": {
                p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (source / "tests").glob("*.py")
            },
            "recipe": recipe,
            "cleanup": {"verified": True, "reason": "No cloud instance created"},
        }
        save_json(folder / "receipt.json", record)
        path = folder / "testbed.zip"
        with urllib.request.urlopen(recipe["url"], timeout=60) as response:
            path.write_bytes(response.read())
        with zipfile.ZipFile(path) as archive:
            if archive.comment.decode() != recipe["revision"]:
                raise ValueError("Official public test archive moved to a different commit")
            for name in archive.namelist():
                parts = PurePosixPath(name).parts
                if parts[0] != recipe["zip_root"] or ".." in parts:
                    raise ValueError("Unexpected public test archive paths")
            record["archive_members"] = len(archive.namelist())
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        target = "/opt/harnesslab-verifier-inputs/" + task + "/testbed.zip"
        archive = folder / "verifier-inputs.tar.gz"
        with tarfile.open(archive, "w:gz") as stream:
            stream.add(path, arcname=target.lstrip("/"))
        record.update(
            ok=True,
            python_downloads={recipe["url"]: {"path": target, "sha256": digest}},
            downloaded_file={"sha256": digest, "bytes": path.stat().st_size},
            archive={
                "archive": str(archive.relative_to(root)),
                "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                "bytes": archive.stat().st_size,
            },
        )
        save_json(folder / "receipt.json", record)
        print(json.dumps(record), flush=True)


if __name__ == "__main__":
    main()
