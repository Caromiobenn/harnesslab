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


def prepare_files(folder, task, recipe):
    downloads, files = {}, {}
    definitions = recipe.get("files") or [{"name": "testbed.zip", "url": recipe["url"]}]
    for item in definitions:
        path = folder / item["name"]
        if path.parent != folder:
            raise ValueError("Use a single filename for each public input")
        with urllib.request.urlopen(item["url"], timeout=60) as response:
            path.write_bytes(response.read())
        data = path.read_bytes()
        if item.get("md5") and hashlib.md5(data, usedforsecurity=False).hexdigest() != item["md5"]:
            raise ValueError("Public input differs from the upstream dataset checksum")
        if item.get("git_blob_sha1"):
            blob = b"blob " + str(len(data)).encode() + b"\0" + data
            if hashlib.sha1(blob, usedforsecurity=False).hexdigest() != item["git_blob_sha1"]:
                raise ValueError("Public input differs from the pinned Git object")
        if "zip_root" in recipe:
            with zipfile.ZipFile(path) as archive:
                if archive.comment.decode() != recipe["revision"]:
                    raise ValueError("Official public test archive moved to a different commit")
                for name in archive.namelist():
                    parts = PurePosixPath(name).parts
                    if parts[0] != recipe["zip_root"] or ".." in parts:
                        raise ValueError("Unexpected public test archive paths")
        target = "/opt/harnesslab-verifier-inputs/" + task + "/" + item["name"]
        digest = hashlib.sha256(data).hexdigest()
        for url in [item["url"], *item.get("aliases", [])]:
            downloads[url] = {"path": target, "sha256": digest}
        files[item["name"]] = {"sha256": digest, "bytes": len(data), "target": target}
    archive = folder / "verifier-inputs.tar.gz"
    with tarfile.open(archive, "w:gz") as stream:
        for name, info in files.items():
            stream.add(folder / name, arcname=info["target"].lstrip("/"))
    return archive, downloads, files


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
        archive, downloads, files = prepare_files(folder, task, recipe)
        record.update(
            ok=True,
            python_downloads={} if recipe.get("transport") == "curl" else downloads,
            cli_downloads=downloads if recipe.get("transport") == "curl" else {},
            verifier_env=recipe.get("verifier_env", {}),
            downloaded_files=files,
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
