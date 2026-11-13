"""Capture changed deliverables against a recorded task filesystem baseline."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tarfile
from pathlib import Path, PurePosixPath


def file_digest(stream):
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def snapshot(root: Path, paths: list[str]) -> dict:
    """Record regular files, directory metadata and links without following links."""
    selected = set()
    for logical in paths:
        name = PurePosixPath(logical)
        if not name.is_absolute() or ".." in name.parts:
            raise ValueError("Capture paths must be absolute without parent traversal")
        path = root
        for part in name.parts[1:]:
            path = path / part
            if path.is_symlink():
                break
        selected.add(path)
        if path.is_dir() and not path.is_symlink():
            for parent, directories, files in os.walk(path, followlinks=False):
                selected.update(Path(parent) / name for name in directories + files)
    records = {}
    for path in sorted(selected):
        name = "/" + path.relative_to(root).as_posix()
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            records[name] = {"kind": "missing"}
            continue
        row = {
            "mode": stat.S_IMODE(metadata.st_mode),
            "uid": metadata.st_uid,
            "gid": metadata.st_gid,
        }
        if stat.S_ISLNK(metadata.st_mode):
            row.update(kind="symlink", target=os.readlink(path))
        elif stat.S_ISREG(metadata.st_mode):
            with path.open("rb") as stream:
                row.update(kind="file", bytes=metadata.st_size, sha256=file_digest(stream))
        elif stat.S_ISDIR(metadata.st_mode):
            row.update(kind="directory")
        else:
            row.update(kind="special", file_type=stat.S_IFMT(metadata.st_mode))
        records[name] = row
    return records


def capture_delta(root: Path, paths: list[str], baseline: dict, archive: Path) -> dict:
    """Save a delta archive plus deletions and the exact bytes archived per file.

    The baseline's template/prerequisite provenance belongs in the trial manifest.
    This function captures filesystem artifacts; it does not checkpoint VM memory.
    """
    for logical in paths:
        path = root / logical.lstrip("/")
        if archive.resolve().is_relative_to(path.resolve()):
            raise ValueError("Store the archive outside the captured paths")
    current = snapshot(root, paths)
    changed = {name: row for name, row in current.items() if baseline.get(name) != row}
    removed = sorted(
        name
        for name, row in baseline.items()
        if row["kind"] != "missing" and current.get(name, {}).get("kind", "missing") == "missing"
    )
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "w:gz", dereference=False) as output:
        for name, row in changed.items():
            if row["kind"] in ("file", "directory", "symlink"):
                output.add(root / name.lstrip("/"), arcname=name.lstrip("/"), recursive=False)
    archived = {}
    with tarfile.open(archive, "r|gz") as source:
        for member in source:
            if member.isfile():
                with source.extractfile(member) as stream:
                    archived["/" + member.name] = {
                        "bytes": member.size,
                        "sha256": file_digest(stream),
                    }
    volatile = [
        name
        for name, row in archived.items()
        if row["sha256"] != current[name]["sha256"] or row["bytes"] != current[name]["bytes"]
    ]
    with archive.open("rb") as stream:
        digest = file_digest(stream)
    return {
        "format": "filesystem-delta-v1",
        "paths": paths,
        "archive": archive.name,
        "sha256": digest,
        "bytes": archive.stat().st_size,
        "baseline_sha256": hashlib.sha256(
            json.dumps(baseline, sort_keys=True).encode()
        ).hexdigest(),
        "changed": changed,
        "removed": removed,
        "archived_files": archived,
        "changed_during_capture": volatile,
        "special_paths": [name for name, row in current.items() if row["kind"] == "special"],
    }
