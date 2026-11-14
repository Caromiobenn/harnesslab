"""Restore saved regular files and directories without executing their contents."""

import hashlib
import json
import os
import tarfile
from pathlib import PurePosixPath

from harnesslab.coding.submission_delta import file_digest, snapshot


def file_members(manifest, archive):
    if (
        manifest["format"] != "filesystem-delta-v1"
        or not manifest["transfer_verified"]
        or manifest["removed"]
        or manifest["changed_during_capture"]
        or manifest["special_paths"]
        or any(row["kind"] not in ("file", "directory") for row in manifest["changed"].values())
    ):
        raise ValueError(
            "File restore requires stable regular files and directories without deletions"
        )
    expected = manifest["changed"]
    found, files = set(), {}
    with tarfile.open(archive) as source:
        for member in source:
            relative = PurePosixPath(member.name)
            name = "/" + relative.as_posix()
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or name in found
                or name not in expected
                or not any(PurePosixPath(name).is_relative_to(path) for path in manifest["paths"])
                or not (member.isfile() or member.isdir())
            ):
                raise ValueError("Archive member is duplicated or outside the captured file delta")
            row = expected[name]
            if member.isfile() != (row["kind"] == "file") or (
                member.mode,
                member.uid,
                member.gid,
            ) != (row["mode"], row["uid"], row["gid"]):
                raise ValueError("Archive member metadata differs from the captured submission")
            if member.isfile():
                with source.extractfile(member) as stream:
                    files[name] = {"bytes": member.size, "sha256": file_digest(stream)}
                if files[name] != {"bytes": row["bytes"], "sha256": row["sha256"]}:
                    raise ValueError("Archived file differs from the captured submission")
            found.add(name)
    if found != set(expected) or files != manifest["archived_files"]:
        raise ValueError("Archive omits part of the captured file delta")


def restore_file_delta(root, baseline, manifest, archive):
    file_members(manifest, archive)
    if (
        hashlib.sha256(json.dumps(baseline, sort_keys=True).encode()).hexdigest()
        != manifest["baseline_sha256"]
        or snapshot(root, manifest["paths"]) != baseline
    ):
        raise ValueError("Fresh filesystem differs from the saved baseline")
    with archive.open("rb") as stream:
        if file_digest(stream) != manifest["sha256"] or archive.stat().st_size != manifest["bytes"]:
            raise ValueError("Saved archive bytes changed before restoration")
    paths = {}
    for name in manifest["changed"]:
        target = root / name.lstrip("/")
        if target.resolve() != root.resolve() / name.lstrip("/"):
            raise ValueError("Restore path traverses a symlink")
        paths[name] = target
    with tarfile.open(archive) as source:
        members = sorted(
            source.getmembers(), key=lambda m: (not m.isdir(), len(PurePosixPath(m.name).parts))
        )
        for member in members:
            target = paths["/" + PurePosixPath(member.name).as_posix()]
            if member.isdir():
                target.mkdir(exist_ok=True)
            else:
                with source.extractfile(member) as content, target.open("wb") as output:
                    while chunk := content.read(1024 * 1024):
                        output.write(chunk)
        for member in reversed(members):
            target = paths["/" + PurePosixPath(member.name).as_posix()]
            os.chown(target, member.uid, member.gid)
            target.chmod(member.mode)
    expected = {**baseline, **manifest["changed"]}
    if snapshot(root, manifest["paths"]) != expected:
        raise ValueError("Restored filesystem differs from the captured submission")
    return {"restored_files": len(manifest["archived_files"]), "model_calls": 0}
