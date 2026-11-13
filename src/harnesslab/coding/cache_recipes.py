"""Extract version-pinned verifier dependencies without executing official tests."""

from __future__ import annotations

import hashlib
import json
import re
import shlex
from pathlib import Path


def uv_recipe(script: str) -> list[str] | None:
    assignments = dict(re.findall(r"^([A-Z_]+)='([^']+)'$", script, re.MULTILINE))
    flat = script.replace("\\\n", " ")
    command = next(
        (line.strip() for line in flat.splitlines() if line.strip().startswith("uvx ")), None
    )
    if command is None:
        return None
    args = shlex.split(command)
    args = args[: args.index("pytest")]
    expanded = []
    for value in args:
        for name, replacement in assignments.items():
            value = value.replace("${" + name + "}", replacement)
        if "$" in value:
            raise ValueError("Verifier recipe contains an unresolved shell variable")
        expanded.append(value)
    return expanded


def recipe_inventory(dataset: Path, revision: str) -> dict:
    provenance = json.loads((dataset / "provenance.json").read_text())
    if provenance["revision"] != revision:
        raise ValueError("Verifier cache source revision differs from the study")
    groups = {}
    custom = []
    for script in sorted((dataset / "tasks").glob("*/tests/test.sh")):
        relative = script.relative_to(dataset).as_posix()
        digest = hashlib.sha256(script.read_bytes()).hexdigest()
        if digest != provenance["files"].get(relative):
            raise ValueError("Official verifier source changed: " + relative)
        task = script.parent.parent.name
        args = uv_recipe(script.read_text())
        if args is None:
            custom.append(task)
            continue
        key = hashlib.sha256(json.dumps(args).encode()).hexdigest()[:12]
        row = groups.setdefault(key, {"args": args, "tasks": [], "test_script_sha256": {}})
        row["tasks"].append(task)
        row["test_script_sha256"][task] = digest
    return {"revision": revision, "groups": groups, "custom": custom}
