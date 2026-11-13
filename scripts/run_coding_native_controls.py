"""Run offline/public empty and reference controls using accepted public caches."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
from pathlib import Path

from harnesslab.coding.config import configure_runtime, load_config, project_root, save_json
from harnesslab.coding.native_controls import official_control_result, task_prerequisites
from harnesslab.coding.runner import execute_stage, preflight_environment, task_plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    parser.add_argument("--cache-ledger", type=Path, required=True)
    parser.add_argument("--task-profiles", type=Path, required=True)
    parser.add_argument("--tasks", nargs="+")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,47}", args.run):
        raise ValueError("Use a short control run name")
    root = project_root()
    configure_runtime(root)
    os.environ.pop("BENCHMARK_NEXT_RUN", None)
    ledger_bytes = args.cache_ledger.read_bytes()
    ledger = json.loads(ledger_bytes)
    profiles = json.loads((root / args.task_profiles).read_text())["tasks"]
    selected = args.tasks or list(profiles)
    folder = root / "artifacts/native-controls" / args.run
    if folder.exists():
        raise ValueError("Inspect the existing control run before choosing another run name")
    config = load_config(root, Path("configs/coding-tb21-full.json"))
    if ledger["benchmark_revision"] != config.revision:
        raise ValueError("Public caches belong to a different benchmark revision")
    rows = [task_plan(root, config, name) for name in selected]
    entries = {
        row["task"]: task_prerequisites(root, row, profiles[row["task"]]["capture_paths"], ledger)
        for row in rows
    }
    manifest = folder / "prerequisites.json"
    save_json(
        manifest,
        {
            "schema_version": 1,
            "benchmark_revision": config.revision,
            "tasks": entries,
            "cache_ledger_sha256": hashlib.sha256(ledger_bytes).hexdigest(),
        },
    )
    (folder / "cache-ledger.json").write_bytes(ledger_bytes)
    config = config.model_copy(
        update={
            "tasks": selected,
            "groups": [],
            "prerequisites_manifest": str(manifest.relative_to(root)),
            "concurrency": 2,
            "repeats": 1,
            "langsmith_tracing": False,
            "purpose": "Official controls of native task environments; no model calls.",
        }
    )
    for row in rows:
        preflight_environment(root, config, row)
    record = {
        "ok": False,
        "model_calls": 0,
        "expected_controls": len(rows) * 4,
        "configuration": config.model_dump(),
        "tasks": rows,
        "source_hashes": {
            path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in [
                *root.glob("src/harnesslab/coding/*.py"),
                *root.glob("vendor/hongkong/*.py"),
                root / "scripts/run_coding_native_controls.py",
                root / args.task_profiles,
                root / "configs/coding-tasks.lock.json",
            ]
        },
        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "outcomes": [],
    }
    save_json(folder / "acceptance.json", record)

    def controls(row, mode):
        current = config.model_copy(update={"network_mode": mode})
        batch = args.run + "-" + mode
        batch_folder = root / "artifacts/coding" / batch
        batch_folder.mkdir(parents=True, exist_ok=True)
        outcomes = []
        for group, expected in (("empty", 0.0), ("oracle", 1.0)):
            outcome = execute_stage(root, batch_folder, row, group, current, batch, 0, False)
            accepted = official_control_result(outcome, expected)
            outcomes.append(accepted)
            if not accepted["control_accepted"]:
                break
        return outcomes

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        pending = {
            pool.submit(controls, row, mode): (row["task"], mode)
            for row in rows
            for mode in ("offline", "public")
        }
        for future in concurrent.futures.as_completed(pending):
            try:
                record["outcomes"].extend(future.result())
            except Exception as exc:
                task, mode = pending[future]
                record["outcomes"].append(
                    {
                        "task": task,
                        "network_mode": mode,
                        "controller_error": f"{type(exc).__name__}: {exc}",
                        "control_accepted": False,
                    }
                )
            save_json(folder / "acceptance.json", record)
    record["ok"] = len(record["outcomes"]) == record["expected_controls"] and all(
        row["control_accepted"] for row in record["outcomes"]
    )
    save_json(folder / "acceptance.json", record)
    print(
        json.dumps(
            {
                "ok": record["ok"],
                "controls": len(record["outcomes"]),
                "accepted": sum(row["control_accepted"] for row in record["outcomes"]),
            }
        ),
        flush=True,
    )
    raise SystemExit(0 if record["ok"] else 1)


if __name__ == "__main__":
    main()
