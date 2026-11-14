"""Validate a labelled public reference repair and its unchanged offline submission."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from harnesslab.coding.config import CodingConfig, configure_runtime, project_root, save_json
from harnesslab.coding.control_reuse import task_contract
from harnesslab.coding.native_controls import official_control_result, task_prerequisites
from harnesslab.coding.reuse import checked_json, digest
from harnesslab.coding.runner import execute_stage, preflight_environment, task_plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--source-acceptance", type=Path, required=True)
    parser.add_argument("--source-sha256", required=True)
    args = parser.parse_args()
    root = project_root()
    configure_runtime(root)
    os.environ.pop("BENCHMARK_NEXT_RUN", None)
    task = "protein-assembly"
    source_path = args.source_root / args.source_acceptance
    source = checked_json(source_path, args.source_sha256)
    original = source["outcomes"]
    if (
        source["model_calls"] != 0
        or len(original) != 4
        or {
            (row.get("task"), row.get("group"), row.get("network_mode"), row.get("repeat"))
            for row in original
        }
        != {
            (task, group, mode, 0)
            for group in ("empty", "oracle")
            for mode in ("offline", "public")
        }
    ):
        raise ValueError("Expected the four completed original protein controls")
    if not all(row["cleanup_verified"] for row in original):
        raise ValueError("Original reference instances have not been reclaimed")
    for name, expected in source["source_hashes"].items():
        if digest(root / name) != expected:
            raise ValueError("Original control runtime changed: " + name)
    empty = [official_control_result(row, 0.0) for row in original if row["group"] == "empty"]
    public = next(
        row for row in original if row["group"] == "oracle" and row["network_mode"] == "public"
    )
    if not all(row["control_accepted"] for row in empty) or public["reward"] != 0.0:
        raise ValueError(
            "Expected accepted empty controls and the recorded public reference failure"
        )
    original_config = CodingConfig.model_validate(source["configuration"])
    row = task_plan(root, original_config, task)
    if task_contract(row) != task_contract(source["tasks"][0]):
        raise ValueError("Official task or resource limits changed")
    inputs = checked_json(source_path.parent / "prerequisites.json", source["manifest_sha256"])
    ledger_path = source_path.parent / "cache-ledger.json"
    ledger = json.loads(ledger_path.read_text())
    profile_path = root / "configs/coding-native-control-profiles.json"
    profile = json.loads(profile_path.read_text())["tasks"][task]
    entry = task_prerequisites(
        root, row, profile["capture_paths"], ledger, profile.get("verifier_env")
    )
    if entry != inputs["tasks"][task]:
        raise ValueError("Public package inputs differ from the original controls")
    folder = root / "artifacts/native-controls" / args.run
    folder.mkdir(parents=True, exist_ok=False)
    manifest = folder / "prerequisites.json"
    manifest.write_bytes((source_path.parent / "prerequisites.json").read_bytes())
    (folder / "cache-ledger.json").write_bytes(ledger_path.read_bytes())
    config = original_config.model_copy(
        update={
            "prerequisites_manifest": str(manifest.relative_to(root)),
            "purpose": "Reference API compatibility and offline grading controls; no model calls.",
        }
    )
    preflight_environment(root, config, row)
    record = {
        "ok": False,
        "model_calls": 0,
        "expected_controls": 4,
        "configuration": config.model_dump(),
        "tasks": [row],
        "source_hashes": {
            name: digest(root / name)
            for name in [
                *source["source_hashes"],
                "src/harnesslab/coding/reference_compat.py",
                "scripts/run_coding_reference_compatibility.py",
            ]
        },
        "manifest_sha256": digest(manifest),
        "original_acceptance": {"path": str(source_path), "sha256": args.source_sha256},
        "reference_network_observations": original,
        "outcomes": [{**item, "control_kind": "original_empty"} for item in empty],
    }
    save_json(folder / "acceptance.json", record)

    def execute(mode, override, kind):
        batch = args.run + "-" + mode
        batch_folder = root / "artifacts/coding" / batch
        batch_folder.mkdir(parents=True, exist_ok=False)
        outcome = execute_stage(
            root,
            batch_folder,
            row,
            "oracle",
            config.model_copy(update={"network_mode": mode}),
            batch,
            0,
            False,
            agent_override=override,
        )
        outcome = {**official_control_result(outcome, 1.0), "control_kind": kind}
        record["outcomes"].append(outcome)
        save_json(folder / "acceptance.json", record)
        if not outcome["control_accepted"]:
            raise SystemExit("Compatibility scoring control failed; original observations retained")
        return outcome

    accepted = execute(
        "public",
        {
            "import_path": "harnesslab.coding.reference_compat:ProteinPublicReferenceControl",
            "kwargs": {
                "task_dir": row["path"],
                "agent_timeout_sec": row["agent_seconds"],
                "network_mode": "public",
                "source_sha256": digest(Path(row["path"]) / "solution/solve.sh"),
            },
        },
        "public_reference_api_compatibility",
    )
    submission = Path(accepted["trial"]) / "agent/submission/manifest.json"
    record["offline_positive_source"] = {"manifest": str(submission), "sha256": digest(submission)}
    execute(
        "offline",
        {
            "import_path": "harnesslab.coding.regrade:FileSubmissionRegrader",
            "kwargs": {
                "network_mode": "offline",
                "source_manifest": str(submission),
                "source_sha256": digest(submission),
            },
        },
        "restored_public_reference_submission",
    )
    record["ok"] = all(item["control_accepted"] for item in record["outcomes"])
    save_json(folder / "acceptance.json", record)
    print(json.dumps({"ok": record["ok"], "accepted_scoring_controls": 4, "model_calls": 0}))


if __name__ == "__main__":
    main()
