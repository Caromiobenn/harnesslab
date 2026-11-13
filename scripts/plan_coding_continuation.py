"""Inventory planned cells and failed attempts without launching or selecting new samples."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from itertools import product
from pathlib import Path

SCHEDULING_FIELDS = {"tasks", "groups", "network_mode", "concurrency", "purpose"}


def read(path):
    return json.loads(path.read_text())


def protocol(config):
    return {key: value for key, value in config.items() if key not in SCHEDULING_FIELDS}


def key_for(row):
    return row["network_mode"], row["task"], row["group"], row["repeat"]


def classify(row):
    # Even a scored harness error cannot become a second sample chosen for a better score.
    if row.get("reward") is not None:
        return "retain_scored" if row["pipeline_ok"] else "retain_score_review_pipeline"
    submission = (row.get("metrics") or {}).get("submission") or {}
    if submission.get("sha256"):
        return "inspect_saved_submission_for_regrade"
    exception = row.get("exception") or {}
    if (
        exception.get("exception_type") == "RuntimeError"
        and "Actor processes did not exit" in exception.get("exception_message", "")
        and row.get("cleanup_verified")
    ):
        return "replace_after_shutdown_fix"
    return "review_unscored_failure"


def make_plan(root, config, batches, networks=("offline", "public")):
    if config["repeats"] != 1:
        raise ValueError("This continuation ledger requires one independent sample per cell")
    planned = set(product(networks, config["tasks"], config["groups"], [0]))
    attempts = defaultdict(list)
    unfinished = defaultdict(list)
    source_plans = []
    model_profile = None
    task_definitions = {}
    for batch in batches:
        folder = root / "artifacts/coding" / batch
        plan_path = folder / "plan.json"
        if not plan_path.exists():
            if list(folder.glob("*.outcome.json")) or list(folder.glob("*.config.json")):
                raise ValueError(f"Attempt records have no immutable plan: {batch}")
            source_plans.append({"batch": batch, "plan_present": False, "summary_present": False})
            continue
        frozen = read(plan_path)
        if protocol(frozen["configuration"]) != protocol(config):
            raise ValueError(f"Model/experiment configuration changed: {batch}")
        profile = {
            name: frozen[name] for name in ("model", "base_url", "api_style", "thinking_body")
        }
        if model_profile is not None and profile != model_profile:
            raise ValueError(f"Model endpoint, snapshot, or thinking request changed: {batch}")
        model_profile = profile
        for task in frozen["tasks"]:
            # Controller paths can change between isolated worktrees; task semantics cannot.
            definition = {name: value for name, value in task.items() if name != "path"}
            previous = task_definitions.setdefault(task["task"], definition)
            if definition != previous:
                raise ValueError(f"Task environment or budgets changed: {task['task']}")
        source_plans.append(
            {
                "batch": batch,
                "plan_present": True,
                "plan_sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
                "summary_present": (folder / "summary.json").exists(),
                "source_hashes": frozen["source_hashes"],
            }
        )
        for path in sorted(folder.glob("*.outcome.json")):
            row = read(path)
            if row.get("group") in ("empty", "oracle"):
                continue
            key = key_for(row)
            if key not in planned:
                raise ValueError(f"Outcome is outside the planned matrix: {key}")
            attempts[key].append(
                {
                    "batch": batch,
                    "job_name": row["job_name"],
                    "outcome_path": str(path),
                    "outcome_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "trial": row.get("trial"),
                    "reward": row.get("reward"),
                    "pipeline_ok": row["pipeline_ok"],
                    "decision": classify(row),
                    "exception_type": (row.get("exception") or {}).get("exception_type"),
                    "cleanup_verified": row.get("cleanup_verified"),
                }
            )
        for path in sorted(folder.glob("*.config.json")):
            name = path.name.removesuffix(".config.json")
            if (folder / f"{name}.outcome.json").exists():
                continue
            stage = read(path)
            agent = stage["agents"][0]
            experiment = agent.get("kwargs", {}).get("experiment")
            if not experiment:
                continue  # Controls have no model sample to repeat.
            task = Path(stage["tasks"][0]["path"]).name
            group = agent["kwargs"].get("group", "mini")
            key = experiment["network_mode"], task, group, 0
            if key not in planned:
                raise ValueError(f"Unfinished attempt is outside the planned matrix: {key}")
            unfinished[key].append({"batch": batch, "job_name": name, "config_path": str(path)})
    cells = []
    for key in sorted(planned):
        rows = attempts[key]
        scored = [row for row in rows if row["reward"] is not None]
        if len(scored) > 1:
            raise ValueError(f"Multiple scored attempts would violate one-sample selection: {key}")
        if scored:
            decision = scored[0]["decision"]
        elif unfinished[key]:
            decision = "wait_or_inspect_unfinished"
        elif rows:
            decision = rows[-1]["decision"]
        else:
            decision = "not_started"
        cells.append(
            {
                "network": key[0],
                "task": key[1],
                "group": key[2],
                "repeat": key[3],
                "decision": decision,
                "attempts": rows,
                "unfinished": unfinished[key],
                "selected_outcome": scored[0]["outcome_path"] if scored else None,
            }
        )
    return {
        "configuration": config,
        "planned_cells": len(planned),
        "model_profile": model_profile,
        "task_definitions": task_definitions,
        "source_plans": source_plans,
        "cells": cells,
        "decision_counts": dict(Counter(cell["decision"] for cell in cells)),
        "execution_authorized_by_this_file": False,
        "rules": [
            "This is an inventory, not a launcher; it does not determine whether a job is live.",
            "Verify owning jobs are terminal and instances cleaned before starting replacements.",
            "Keep every original attempt and its usage, including infrastructure failures.",
            "Keep official zero scores and deadline results; never select a better rerun.",
            "Inspect saved submissions for artifact-only regrading before another model call.",
            "Record replacement source hashes and the exact infrastructure-only change separately.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--config", default="configs/coding-tb21-study.json")
    parser.add_argument("--batches", nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = make_plan(args.root, read(args.root / args.config), args.batches)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2))
    print(json.dumps({key: result[key] for key in ("planned_cells", "decision_counts")}))


if __name__ == "__main__":
    main()
