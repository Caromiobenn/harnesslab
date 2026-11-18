"""Compare a runnable-draft instruction with standard solving at equal caps."""

import argparse
import hashlib
import json
import random
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from phase2.tasks import study_tasks  # noqa: E402
from run_study import DraftWorkflow, checked, read_env, run_trial, write_json  # noqa: E402
from study_client import BASE_URL, MODEL  # noqa: E402

WORKFLOWS = {
    "standard": DraftWorkflow("standard"),
    "early_draft": DraftWorkflow(
        "early_draft",
        "Prioritize an end-to-end runnable draft. As soon as it runs the public example "
        "with the expected output, call record_draft before doing further checks, polishing "
        "or optimization. Continue testing and improving the draft against the original "
        "requirements after marking it, and provide the normal final response when done.",
    ),
}
TASKS = ("inventory-aging", "route-ledger")
ORDER_SEED = 18118


def design(args, cells):
    source_files = (
        Path(__file__).resolve(),
        ROOT / "run_study.py",
        ROOT / "study_client.py",
        Path(study_tasks.__file__).resolve(),
    )
    return {
        "cells": cells,
        "workflows": {name: item.instruction for name, item in WORKFLOWS.items()},
        "model": args.model,
        "provider": args.base_url,
        "reasoning": "disabled",
        "temperature": 0.3,
        "score_seed": args.score_seed,
        "order_seed": ORDER_SEED,
        "response_cap": args.max_responses,
        "token_cap_per_response": args.max_tokens,
        "time_budget_seconds": args.timeout,
        "shared_draft_tool": "record_draft",
        "last_snapshot_is_final": True,
        "workers": args.workers,
        "source_sha256": {
            p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in source_files
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--workers", type=int, default=6, choices=range(1, 9))
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args()
    args.suite = "phase2"
    args.model, args.base_url = MODEL, BASE_URL
    args.actor_image = "tb21-integrity-actor:pilot1"
    args.scorer_image = "tb21-integrity-scorer:pilot1"
    args.max_responses, args.max_tokens, args.timeout = 20, 4096, 210
    args.review, args.review_max_responses, args.trace = False, 0, True
    args.score_seed = 18053
    cells = [
        (arm, task, requirement, toolchain, repeat)
        for arm in WORKFLOWS
        for task in TASKS
        for requirement in study_tasks.REQUIREMENTS
        for toolchain in study_tasks.TOOLCHAINS
        for repeat in (1, 2)
    ]
    random.Random(ORDER_SEED).shuffle(cells)
    plan = design(args, cells)
    if args.plan:
        print(json.dumps(plan, indent=2))
        return
    if args.env_file is None or args.out is None:
        parser.error("choose --env-file and a fresh --out directory")
    config = read_env(args.env_file)
    for label in ("actor_image", "scorer_image"):
        tag = getattr(args, label)
        fingerprint = checked("image", "inspect", "--format", "{{.Id}}", tag)
        plan[label + "_id"] = fingerprint
        setattr(args, label, fingerprint)
    out = args.out.resolve()
    out.mkdir(parents=True)
    for arm in WORKFLOWS:
        (out / arm).mkdir()
    write_json(out / "design.json", plan)
    score_script = Path(study_tasks.__file__).read_bytes()
    rows = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        future = [
            pool.submit(
                run_trial,
                args,
                cell,
                out / arm,
                config,
                study_tasks,
                score_script,
                workflow=WORKFLOWS[arm],
            )
            for arm, *cell in cells
        ]
        for item in as_completed(future):
            row = item.result()
            rows.append(row)
            write_json(out / "results.json", rows)
            print(
                row["workflow"],
                row["task"],
                row["requirement"],
                row["toolchain"],
                row["repeat"],
                row["status"],
                row["score_status"],
                "qualified=",
                row["score"].get("qualified"),
                flush=True,
            )


if __name__ == "__main__":
    main()
