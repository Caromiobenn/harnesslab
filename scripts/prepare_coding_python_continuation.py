"""Move retired, unstarted units to the accepted Python runtime without resampling."""

from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
from pathlib import Path

from harnesslab.coding.config import CodingConfig, configure_runtime, project_root, save_json
from harnesslab.coding.control_reuse import load_control_reuse, source_differences
from harnesslab.coding.reuse import checked_json, digest
from harnesslab.coding.runner import build_plan


def replacement_units(studies: list[tuple[Path, dict, list[int]]]) -> list[tuple[Path, dict]]:
    result, seen = [], set()
    for root, study, indices in studies:
        for index in indices:
            unit = study["units"][index]
            if (root / "artifacts/coding" / unit["batch"]).exists():
                raise ValueError("Replacement unit already has an execution directory")
            cells = {(unit["network"], unit["task"], group, 0) for group in unit["groups"]}
            if not cells or len(cells) != len(unit["groups"]) or cells & seen:
                raise ValueError("Replacement cells overlap")
            seen.update(cells)
            result.append((root, unit))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--run", required=True)
    args = parser.parse_args()
    root = project_root()
    configure_runtime(root)
    selection = json.loads(args.selection.read_text())
    retired = checked_json(selection["retirement"], selection["retirement_sha256"])
    if not retired["verified"] or not retired["all_selected_cancelled"]:
        raise ValueError("Retire the held units before replacing them")
    acceptance = selection["acceptance"]
    accepted = checked_json(acceptance["path"], acceptance["sha256"])
    if not accepted["ok"] or accepted["model_calls"]:
        raise ValueError("Python runtime cloud acceptance is incomplete")
    references = retired["studies"]
    studies = []
    old_controls, entries, task_origins = {}, {}, {}
    for reference in references:
        origin = Path(reference["root"])
        previous = checked_json(origin / reference["study"], reference["sha256"])
        for name, sha in {**previous["source_hashes"], **previous["script_hashes"]}.items():
            if digest(origin / name) != sha:
                raise ValueError("Frozen predecessor changed: " + name)
        studies.append((origin, previous, reference["units"]))
        controls = checked_json(origin / previous["controls_manifest"], previous["controls_sha256"])
        for index in reference["units"]:
            unit = previous["units"][index]
            task = unit["task"]
            if task in entries:
                continue
            config = checked_json(origin / unit["config"], unit["config_sha256"])
            name = config["prerequisites_manifest"]
            inputs = checked_json(origin / name, previous["source_hashes"][name])
            entries[task] = {**inputs["tasks"][task], "actor_python_fallback": True}
            task_origins[task] = origin
            old_controls[task] = next(row for row in controls["references"] if row["task"] == task)
    replacements = replacement_units(studies)
    latest = checked_json(selection["latest_study"], selection["latest_sha256"])
    full = CodingConfig.model_validate(latest["configuration"])
    if full.repeats != 1 or full.reasoning_effort != "high":
        raise ValueError("Continuation must preserve HIGH and one independent attempt")
    if any(study["configuration"] != full.model_dump() for _, study, _ in studies):
        raise ValueError("Predecessor model protocols disagree")
    folder = root / "artifacts/expansions" / args.run
    folder.mkdir(parents=True, exist_ok=False)
    for task, entry in entries.items():
        for artifact in [*entry["archives"], *entry["verifier"]["archives"]]:
            original = task_origins[task] / artifact["archive"]
            destination = root / artifact["archive"]
            if (
                not destination.resolve().is_relative_to(root)
                or digest(original) != artifact["sha256"]
            ):
                raise ValueError("Public prerequisite archive changed or escaped the workspace")
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.exists():
                os.link(original, destination)
            if digest(destination) != artifact["sha256"]:
                raise ValueError("Copied prerequisite archive differs")
    prerequisites = folder / "prerequisites.json"
    save_json(
        prerequisites, {"schema_version": 1, "benchmark_revision": full.revision, "tasks": entries}
    )
    selected = [task for task in full.tasks if task in entries]
    config = full.model_copy(
        update={
            "tasks": selected,
            "concurrency": 1,
            "prerequisites_manifest": str(prerequisites.relative_to(root)),
        }
    )
    plan = build_plan(root, config)
    profile = {key: plan[key] for key in ("model", "base_url", "api_style", "thinking_body")}
    if any(study["model_profile"] != profile for _, study, _ in studies):
        raise ValueError("Model endpoint or thinking settings changed")
    controls = folder / "controls.json"
    reviewed = []
    for task in selected:
        reference = copy.deepcopy(old_controls[task])
        source = checked_json(reference["acceptance_path"], reference["acceptance_sha256"])
        reference.update(
            actor_python_amendment=acceptance,
            reviewed_source_differences=source_differences(
                source["source_hashes"], plan["source_hashes"]
            ),
            compatibility_reason=(
                "Preserve task, cache bytes, verifier, network and limits; "
                "opt into the cloud-accepted Python fallback. "
                "Record the new runtime cohort separately."
            ),
        )
        reviewed.append(reference)
    save_json(controls, {"target_source_hashes": plan["source_hashes"], "references": reviewed})
    for mode in ("offline", "public"):
        checked_plan = {**plan, "configuration": {**plan["configuration"], "network_mode": mode}}
        if len(load_control_reuse(root, controls, checked_plan)) != 2 * len(selected):
            raise ValueError("Missing official controls")
    units = []
    for index, (origin, prior) in enumerate(replacements):
        unit_config = config.model_copy(
            update={
                "tasks": [prior["task"]],
                "groups": prior["groups"],
                "network_mode": prior["network"],
            }
        )
        path = folder / "configs" / f"{index:03}.json"
        save_json(path, unit_config.model_dump())
        units.append(
            {
                **prior,
                "index": index,
                "config": str(path.relative_to(root)),
                "config_sha256": digest(path),
                "batch": f"{args.run}-{prior['network']}-{index:03}",
                "replaces": {"root": str(origin), "batch": prior["batch"], "index": prior["index"]},
            }
        )
    cells = sum(len(unit["groups"]) for unit in units)
    study = {
        **latest,
        "run": args.run,
        "git_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip(),
        "source_hashes": plan["source_hashes"],
        "model_profile": profile,
        "script_hashes": {
            name: digest(root / name)
            for name in (
                "scripts/prepare_coding_python_continuation.py",
                "scripts/run_coding_expansion_unit.py",
            )
        },
        "controls_manifest": str(controls.relative_to(root)),
        "controls_sha256": digest(controls),
        "control_sources": [],
        "ready_tasks": selected,
        "units": units,
        "new_model_cells": cells,
        "prior_studies": [
            {"origin": selection["latest_study"], "sha256": selection["latest_sha256"]}
        ],
        "reserved_prior_tasks": [
            task for task in full.tasks if task not in entries and task not in latest["pilot_tasks"]
        ],
        "reserved_prior_cells": latest["full_model_cells"]
        - latest["preserved_pilot_cells"]
        - cells,
        "pending_tasks": [],
        "python_amendment": {
            "acceptance": acceptance,
            "retirement": {
                "path": selection["retirement"],
                "sha256": selection["retirement_sha256"],
            },
            "only_unstarted_units": True,
        },
    }
    save_json(folder / "study.json", study)
    print(
        json.dumps(
            {
                "study": str(folder / "study.json"),
                "sha256": digest(folder / "study.json"),
                "units": len(units),
                "new_model_cells": cells,
                "model_calls": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
