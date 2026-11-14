"""Explicit, hash-checked references to compatible completed samples."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from harnesslab.coding.config import save_json

SCHEDULING_FIELDS = {"tasks", "groups", "network_mode", "concurrency", "purpose"}


def protocol(configuration):
    return {key: value for key, value in configuration.items() if key not in SCHEDULING_FIELDS}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cell(row):
    return row["network_mode"], row["task"], row["group"], row["repeat"]


def checked_json(path, expected):
    path = Path(path)
    if digest(path) != expected:
        raise ValueError(f"Reused record changed: {path}")
    return json.loads(path.read_text())


def load_reuse(path: Path, target_plan: dict) -> dict:
    """Validate a reviewed compatibility manifest before any new cloud work."""
    manifest = json.loads(path.read_text())
    if manifest["target_source_hashes"] != target_plan["source_hashes"]:
        raise ValueError("Continuation source changed; review compatibility again")
    if target_plan["configuration"]["repeats"] != 1:
        raise ValueError("Continuation requires one independent sample per cell")
    target_tasks = {row["task"]: row for row in target_plan["tasks"]}
    references = {}
    for entry in manifest["references"]:
        row = checked_json(entry["outcome_path"], entry["outcome_sha256"])
        source = checked_json(entry["plan_path"], entry["plan_sha256"])
        if row["group"] not in entry["compatible_groups"]:
            raise ValueError("Group is not covered by the reviewed source compatibility")
        if protocol(source["configuration"]) != protocol(target_plan["configuration"]):
            raise ValueError("Reused model configuration changed")
        for key in ("model", "base_url", "api_style", "thinking_body"):
            if source[key] != target_plan[key]:
                raise ValueError(f"Reused model profile changed: {key}")
        differences = {
            key: {
                "before": source["source_hashes"].get(key),
                "after": target_plan["source_hashes"].get(key),
            }
            for key in source["source_hashes"].keys() | target_plan["source_hashes"].keys()
            if source["source_hashes"].get(key) != target_plan["source_hashes"].get(key)
        }
        if differences != entry["reviewed_source_differences"] or not entry["compatibility_reason"]:
            raise ValueError("Source differences have not been reviewed")
        if row["network_mode"] != source["configuration"]["network_mode"]:
            raise ValueError("Reused network condition differs from its source plan")
        original = next(task for task in source["tasks"] if task["task"] == row["task"])
        target = target_tasks.get(row["task"])
        if target is None:
            continue
        if {k: v for k, v in original.items() if k != "path"} != {
            k: v for k, v in target.items() if k != "path"
        }:
            raise ValueError("Reused task environment or time budgets changed")
        if row["reward"] is None or not row["cleanup_verified"]:
            raise ValueError("Reuse requires an official score and verified cleanup")
        if row["group"] in ("empty", "oracle"):
            expected = int(row["group"] == "oracle")
            if not row["pipeline_ok"] or row["reward"] != expected:
                raise ValueError("A failed control cannot authorize model execution")
        key = cell(row)
        if key in references:
            raise ValueError(f"Multiple source samples for cell: {key}")
        references[key] = {"outcome": row, "reference": entry}
    return references


def save_reused(folder: Path, batch: str, reference: dict, resume: bool) -> dict:
    original = reference["outcome"]
    entry = reference["reference"]
    # Keep the original job/trial, verdict, metrics and trace identity intact.
    outcome = {
        **original,
        "reuse": {
            "source_outcome": entry["outcome_path"],
            "source_sha256": entry["outcome_sha256"],
            "source_plan": entry["plan_path"],
            "source_plan_sha256": entry["plan_sha256"],
            "reason": entry["compatibility_reason"],
        },
    }
    path = (
        folder / f"{batch}-{original['task']}-{original['group']}-{original['repeat']}.outcome.json"
    )
    if path.exists() and (not resume or json.loads(path.read_text()) != outcome):
        raise ValueError("Existing reused outcome changed or needs --resume")
    save_json(path, outcome)
    return outcome
