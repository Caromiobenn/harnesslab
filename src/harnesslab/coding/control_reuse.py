"""Reuse executed native controls when task inputs and reviewed runtime remain compatible."""

from __future__ import annotations

import json
from pathlib import Path

from harnesslab.coding.config import save_json
from harnesslab.coding.native_controls import official_control_result
from harnesslab.coding.reuse import cell, checked_json


def source_differences(before: dict, after: dict) -> dict:
    return {
        name: {"before": before.get(name), "after": after.get(name)}
        for name in before.keys() | after.keys()
        if before.get(name) != after.get(name)
    }


def task_contract(row: dict) -> dict:
    return {name: value for name, value in row.items() if name != "path"}


def check_prerequisites(before: dict, after: dict, entry: dict, source_hashes: dict) -> None:
    if before == after:
        return
    amendment = entry.get("actor_python_amendment")
    if (
        not amendment
        or before.get("actor_python_fallback", False)
        or after != {**before, "actor_python_fallback": True}
    ):
        raise ValueError("Control task prerequisites changed")
    accepted = checked_json(amendment["path"], amendment["sha256"])
    runtime = "src/harnesslab/coding/native_environment.py"
    if (
        not accepted["ok"]
        or accepted["model_calls"] != 0
        or accepted["runtime_sha256"] != source_hashes[runtime]
        or {row["mode"] for row in accepted["probes"]} != {"offline", "public"}
        or len(accepted["probes"]) != 2
        or not all(row["ok"] and row["cleanup_verified"] for row in accepted["probes"])
        or len(accepted["controls"]) != 4
        or {(row["network_mode"], row["group"]) for row in accepted["controls"]}
        != {(mode, group) for mode in ("offline", "public") for group in ("empty", "oracle")}
        or not all(
            official_control_result(row, float(row["group"] == "oracle"))["control_accepted"]
            for row in accepted["controls"]
        )
    ):
        raise ValueError("Python runtime amendment lacks accepted cloud checks")


def load_control_reuse(root: Path, path: Path, target_plan: dict) -> dict:
    """Validate controls separately from model samples; never replace a model attempt."""
    manifest = json.loads(path.read_text())
    if manifest["target_source_hashes"] != target_plan["source_hashes"]:
        raise ValueError("Control continuation source changed")
    configuration = target_plan["configuration"]
    name = configuration["prerequisites_manifest"]
    target_inputs = checked_json(root / name, target_plan["source_hashes"][name])
    targets = {row["task"]: row for row in target_plan["tasks"]}
    references = {}
    for entry in manifest["references"]:
        task = entry["task"]
        if task not in targets:
            continue
        source = checked_json(entry["acceptance_path"], entry["acceptance_sha256"])
        if source["model_calls"] != 0 or any(
            source["configuration"][key] != configuration[key] for key in ("benchmark", "revision")
        ):
            raise ValueError("Control benchmark identity changed")
        source_task = next(row for row in source["tasks"] if row["task"] == task)
        if task_contract(source_task) != task_contract(targets[task]):
            raise ValueError("Control task image or time budget changed")
        inputs = checked_json(entry["prerequisites_path"], source["manifest_sha256"])
        check_prerequisites(
            inputs["tasks"][task], target_inputs["tasks"][task], entry, target_plan["source_hashes"]
        )
        differences = source_differences(source["source_hashes"], target_plan["source_hashes"])
        if differences != entry["reviewed_source_differences"] or not entry["compatibility_reason"]:
            raise ValueError("Control runtime differences need an explicit compatibility review")
        for group, expected in (("empty", 0.0), ("oracle", 1.0)):
            rows = [
                row
                for row in source["outcomes"]
                if row.get("task") == task
                and row.get("network_mode") == configuration["network_mode"]
                and row.get("group") == group
                and row.get("repeat") == 0
            ]
            if len(rows) != 1:
                raise ValueError("A control cell must have exactly one accepted source")
            row = rows[0]
            actual = official_control_result(row, expected)
            if (
                not row["control_accepted"]
                or not actual["control_accepted"]
                or actual["ctrf_summary"] != row["ctrf_summary"]
            ):
                raise ValueError("Reused control lacks matching executed official assertions")
            key = cell(row)
            if key in references:
                raise ValueError("Duplicate reused control cell")
            references[key] = {
                **row,
                "control_reuse": {
                    "acceptance": entry["acceptance_path"],
                    "acceptance_sha256": entry["acceptance_sha256"],
                    "prerequisites": entry["prerequisites_path"],
                    "prerequisites_sha256": source["manifest_sha256"],
                    "reason": entry["compatibility_reason"],
                    "actor_python_amendment": entry.get("actor_python_amendment"),
                },
            }
    return references


def save_reused_control(folder: Path, batch: str, row: dict, resume: bool) -> dict:
    path = folder / f"{batch}-{row['task']}-{row['group']}-{row['repeat']}.outcome.json"
    if path.exists() and (not resume or json.loads(path.read_text()) != row):
        raise ValueError("Existing reused control changed or needs --resume")
    save_json(path, row)
    return row
