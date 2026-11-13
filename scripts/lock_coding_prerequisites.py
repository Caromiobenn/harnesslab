"""Lock successful public prerequisites from one or more preparation runs."""

import argparse
import hashlib
import json

from harnesslab.coding.config import configure_runtime, load_config, project_root, save_json
from harnesslab.coding.runner import task_plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", nargs="+", required=True)
    parser.add_argument("--output", default="configs/coding-prerequisites.lock.json")
    args = parser.parse_args()
    root = project_root()
    configure_runtime(root)
    config = load_config(root)
    selected = {}
    for run in args.runs:
        folder = root / "artifacts/coding-prerequisites" / run
        for task in config.tasks:
            receipt = folder / task / "receipt.json"
            if not receipt.exists():
                continue
            entry = json.loads(receipt.read_text())
            if not entry.get("ok") or not entry.get("cleanup_verified"):
                continue
            row = task_plan(root, config, task)
            if entry["source_fingerprint"] != row["source_fingerprint"]:
                raise ValueError(f"Task environment changed: {task}")
            with (root / entry["archive"]).open("rb") as stream:
                actual = hashlib.file_digest(stream, "sha256").hexdigest()
            if actual != entry["sha256"]:
                raise ValueError(f"Archive content changed: {task}")
            selected[task] = {
                **entry,
                "receipt": receipt.relative_to(root).as_posix(),
                "receipt_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
            }
    missing = set(config.tasks) - set(selected)
    if missing:
        raise ValueError("Missing accepted prerequisites: " + ", ".join(sorted(missing)))
    save_json(
        root / args.output,
        {
            "benchmark": config.benchmark,
            "revision": config.revision,
            "purpose": "Identical public dependencies/source fixtures for both network arms",
            "tasks": selected,
        },
    )
    print(json.dumps({"manifest": args.output, "tasks": len(selected)}))


if __name__ == "__main__":
    main()
