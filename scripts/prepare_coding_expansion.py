"""Freeze ready task inputs, accepted controls and execution units for full-study expansion."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

from harnesslab.coding.config import configure_runtime, load_config, project_root, save_json
from harnesslab.coding.control_reuse import load_control_reuse, source_differences
from harnesslab.coding.native_controls import official_control_result
from harnesslab.coding.reuse import checked_json, digest
from harnesslab.coding.runner import build_plan
from harnesslab.coding.transport_amendment import (
    inherited_transport_attempts,
    reserve_transport_attempts,
)


def execution_units(rows: list[dict], groups: list[str], wall_seconds: int = 43200) -> list[dict]:
    units = []
    for row in rows:
        bound = int(
            row["agent_seconds"] + row["verifier_seconds"] + 2 * row["build_seconds"] + 1800
        )
        count = min(len(groups), (wall_seconds - 900) // bound)
        if count < 1:
            raise ValueError("One cell exceeds the selected controller wall-time limit")
        for start in range(0, len(groups), count):
            selected = groups[start : start + count]
            for network in ("offline", "public"):
                units.append(
                    {
                        "task": row["task"],
                        "groups": selected,
                        "network": network,
                        "timeout_bound_seconds": bound * len(selected) + 900,
                    }
                )
    return units


def prior_reservations(
    full: dict,
    selection: dict,
    model_profile: dict,
    folder: Path,
    selected: set[str],
    initial_reserved: set[str] | None = None,
) -> tuple[set[str], list[dict]]:
    """Reserve every cell of earlier batches before preparing additional tasks."""
    reserved, snapshots = set(initial_reserved or ()), []
    for index, reference in enumerate(selection.get("prior_studies", [])):
        origin = Path(reference["root"])
        path = origin / reference["study"]
        previous = checked_json(path, reference["sha256"])
        if previous["configuration"] != full or previous["model_profile"] != model_profile:
            raise ValueError("Previous expansion uses a different study protocol or model")
        if (
            set(previous["pilot_tasks"]) != set(selection["pilot_tasks"])
            or previous["pilot_batches"] != selection["pilot_batches"]
            or not set(previous.get("reserved_prior_tasks", [])) <= reserved
        ):
            raise ValueError("Provide every preceding expansion in order with the same pilot")
        tasks = set(previous["ready_tasks"])
        if (
            len(tasks) != len(previous["ready_tasks"])
            or tasks & (reserved | set(selection["pilot_tasks"]))
            or not tasks <= set(full["tasks"])
        ):
            raise ValueError("Previous expansion contains duplicated or out-of-scope tasks")
        expected = {
            (task, mode, group)
            for task in tasks
            for mode in ("offline", "public")
            for group in full["groups"]
        }
        cells = [
            (unit["task"], unit["network"], group)
            for unit in previous["units"]
            for group in unit["groups"]
        ]
        if len(cells) != len(expected) or set(cells) != expected:
            raise ValueError("Previous expansion has missing or duplicated execution cells")
        if previous["new_model_cells"] != len(expected):
            raise ValueError("Previous expansion cell count does not match its units")
        for name, sha in {**previous["source_hashes"], **previous["script_hashes"]}.items():
            if digest(origin / name) != sha:
                raise ValueError("Previous expansion source changed: " + name)
        snapshot = folder / "prior-studies" / f"{index:02}.json"
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_bytes(path.read_bytes())
        snapshots.append(
            {
                "origin": str(path),
                "sha256": reference["sha256"],
                "snapshot": str(snapshot),
                "run": previous["run"],
                "tasks": sorted(tasks),
                "model_cells": len(cells),
            }
        )
        reserved.update(tasks)
    if reserved & selected:
        raise ValueError("New expansion would resample tasks reserved by an earlier batch")
    return reserved, snapshots


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--run", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,39}", args.run):
        raise ValueError("Use a short expansion run name")
    root = project_root()
    configure_runtime(root)
    full = load_config(root, Path("configs/coding-tb21-full.json"))
    if full.repeats != 1 or full.reasoning_effort != "high":
        raise ValueError("This expansion is the HIGH, one-attempt study")
    selection = json.loads(args.selection.read_text())
    if selection.get("transport_amendment"):
        full = full.model_copy(update={"response_transport": "streaming"})
    elif selection.get("prior_studies"):
        first = selection["prior_studies"][0]
        previous = checked_json(Path(first["root"]) / first["study"], first["sha256"])
        if previous.get("transport_amendment"):
            full = full.model_copy(update={"response_transport": "streaming"})
    folder = root / "artifacts/expansions" / args.run
    if folder.exists():
        raise ValueError("Expansion plans are immutable; inspect the existing plan first")
    folder.mkdir(parents=True)
    entries, references, sources, copied = {}, [], [], {}
    expected_cells = {
        (network, group) for network in ("offline", "public") for group in ("empty", "oracle")
    }
    for index, source in enumerate(selection["controls"]):
        origin = Path(source["root"])
        acceptance_path = origin / source["acceptance"]
        content = acceptance_path.read_bytes()
        accepted = json.loads(content)
        for name, sha in accepted["source_hashes"].items():
            if digest(origin / name) != sha:
                raise ValueError("Control source changed: " + str(origin / name))
        inputs_path = acceptance_path.parent / "prerequisites.json"
        inputs = checked_json(inputs_path, accepted["manifest_sha256"])
        snapshot = folder / "control-sources" / f"{index:02}.json"
        snapshot_inputs = folder / "control-sources" / f"{index:02}-inputs.json"
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_bytes(content)
        snapshot_inputs.write_bytes(inputs_path.read_bytes())
        sources.append(
            {
                "origin": str(acceptance_path),
                "sha256": digest(snapshot),
                "snapshot": str(snapshot.relative_to(root)),
                "tasks": source["tasks"],
            }
        )
        for task in source["tasks"]:
            rows = [row for row in accepted["outcomes"] if row.get("task") == task]
            cells = {(row.get("network_mode"), row.get("group")) for row in rows}
            if (
                len(rows) != 4
                or cells != expected_cells
                or not all(
                    official_control_result(row, float(row["group"] == "oracle"))[
                        "control_accepted"
                    ]
                    for row in rows
                )
            ):
                raise ValueError("Task does not have four accepted controls: " + task)
            if task in entries or task in selection["pilot_tasks"] or task not in full.tasks:
                raise ValueError("Task is duplicated or outside the expansion scope: " + task)
            entry = inputs["tasks"][task]
            for archive in [*entry["archives"], *entry["verifier"]["archives"]]:
                relative = archive["archive"]
                destination = root / relative
                if not destination.resolve().is_relative_to(root):
                    raise ValueError("Archive path is outside the study workspace")
                if relative in copied:
                    if copied[relative] != archive["sha256"]:
                        raise ValueError("Two controls disagree about a public archive")
                    continue
                original = origin / relative
                with original.open("rb") as stream:
                    if hashlib.file_digest(stream, "sha256").hexdigest() != archive["sha256"]:
                        raise ValueError("Source public archive changed")
                destination.parent.mkdir(parents=True, exist_ok=True)
                if not destination.exists():
                    os.link(original, destination)
                with destination.open("rb") as stream:
                    if hashlib.file_digest(stream, "sha256").hexdigest() != archive["sha256"]:
                        raise ValueError("Linked public archive changed")
                copied[relative] = archive["sha256"]
            entries[task] = entry
            references.append(
                {
                    "task": task,
                    "acceptance_path": str(snapshot),
                    "acceptance_sha256": digest(snapshot),
                    "prerequisites_path": str(snapshot_inputs),
                    "compatibility_reason": source["compatibility_reason"],
                    "source_hashes": accepted["source_hashes"],
                }
            )
    selected = [task for task in full.tasks if task in entries]
    if not selected:
        raise ValueError("Select at least one ready task")
    prerequisites = folder / "prerequisites.json"
    save_json(
        prerequisites, {"schema_version": 1, "benchmark_revision": full.revision, "tasks": entries}
    )
    config = full.model_copy(
        update={
            "tasks": selected,
            "concurrency": 1,
            "prerequisites_manifest": str(prerequisites.relative_to(root)),
        }
    )
    plan = build_plan(root, config)
    profile = {key: plan[key] for key in ("model", "base_url", "api_style", "thinking_body")}
    retained, transport_amendment = reserve_transport_attempts(
        full.model_dump(), selection, profile, folder, set(selected)
    )
    if transport_amendment is None:
        retained, transport_amendment = inherited_transport_attempts(
            full.model_dump(), selection, profile, folder, set(selected)
        )
    reserved, prior_studies = prior_reservations(
        full.model_dump(), selection, profile, folder, set(selected), initial_reserved=retained
    )
    for reference in references:
        reference["reviewed_source_differences"] = source_differences(
            reference.pop("source_hashes"), plan["source_hashes"]
        )
    controls = folder / "controls.json"
    save_json(controls, {"target_source_hashes": plan["source_hashes"], "references": references})
    for network in ("offline", "public"):
        checked_plan = {**plan, "configuration": {**plan["configuration"], "network_mode": network}}
        reused = load_control_reuse(root, controls, checked_plan)
        if len(reused) != 2 * len(selected):
            raise ValueError("Missing accepted controls in one network arm")
    units = execution_units(plan["tasks"], list(full.groups))
    for index, unit in enumerate(units):
        unit_config = config.model_copy(
            update={
                "tasks": [unit["task"]],
                "groups": unit["groups"],
                "network_mode": unit["network"],
            }
        )
        path = folder / "configs" / f"{index:03}.json"
        save_json(path, unit_config.model_dump())
        unit.update(
            index=index,
            config=str(path.relative_to(root)),
            config_sha256=digest(path),
            batch=f"{args.run}-{unit['network']}-{index:03}",
        )
    study = {
        "schema_version": 1,
        "run": args.run,
        "git_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip(),
        "configuration": full.model_dump(),
        "source_hashes": plan["source_hashes"],
        "model_profile": profile,
        "script_hashes": {
            name: digest(root / name)
            for name in (
                "scripts/prepare_coding_expansion.py",
                "scripts/run_coding_expansion_unit.py",
            )
        },
        "controls_manifest": str(controls.relative_to(root)),
        "controls_sha256": digest(controls),
        "control_sources": sources,
        "pilot_tasks": selection["pilot_tasks"],
        "pilot_batches": selection["pilot_batches"],
        "ready_tasks": selected,
        "prior_studies": prior_studies,
        "transport_amendment": transport_amendment,
        "reserved_prior_tasks": sorted(reserved),
        "reserved_prior_cells": len(reserved) * len(full.groups) * 2,
        "pending_tasks": [
            task
            for task in full.tasks
            if task not in entries and task not in selection["pilot_tasks"] and task not in reserved
        ],
        "full_model_cells": len(full.tasks) * len(full.groups) * 2,
        "preserved_pilot_cells": len(selection["pilot_tasks"]) * len(full.groups) * 2,
        "new_model_cells": len(selected) * len(full.groups) * 2,
        "array_concurrency": 2,
        "wall_seconds": 43200,
        "units": units,
    }
    save_json(folder / "study.json", study)
    print(
        json.dumps(
            {
                "study": str(folder / "study.json"),
                "ready_tasks": len(selected),
                "pending_tasks": len(study["pending_tasks"]),
                "new_model_cells": study["new_model_cells"],
                "units": len(units),
                "model_calls": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
