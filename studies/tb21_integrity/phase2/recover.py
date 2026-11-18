"""Retry known request transport failures and select one attempt per study cell."""

import argparse
import hashlib
import importlib
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from types import SimpleNamespace

STUDY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STUDY))
from run_study import read_env, run_trial, write_json  # noqa: E402

KEYS = ("task", "requirement", "toolchain", "repeat")
TRANSPORT_ERRORS = {
    "Remote end closed connection without response",
    "DashScope request timed out or was unreachable",
}


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def key(row):
    return tuple(row[k] for k in KEYS)


def eligible(row):
    return row["status"] == "pipeline_error" and row.get("error") in TRANSPORT_ERRORS


def trial_dir(cell):
    task, requirement, toolchain, repeat = cell
    return f"{task}--{requirement}--{toolchain}--r{repeat}"


def retry(original, output, env_path, workers):
    design_path = original / "design.json"
    design = load(design_path)
    cells = [key(row) for row in load(original / "results.json") if eligible(row)]
    if not cells:
        raise ValueError("The batch has no eligible request transport failures")
    if design["suite"] != "phase2" or any(
        sha(STUDY / name) != fingerprint for name, fingerprint in design["source_sha256"].items()
    ):
        raise ValueError("The current study source differs from the frozen phase-two design")
    output.mkdir(parents=True)
    write_json(
        output / "design.json",
        {
            **design,
            "cells": cells,
            "attempt": "replacement_for_transport_error",
            "original_design_sha256": sha(design_path),
        },
    )
    args = SimpleNamespace(
        suite=design["suite"],
        base_url=design["provider"],
        model=design["model"],
        env_file=env_path,
        actor_image=design["actor_image_id"],
        scorer_image=design["scorer_image_id"],
        score_seed=design["score_seed"],
        max_tokens=design["max_tokens_per_response"],
        max_responses=design["max_responses"],
        timeout=design["time_budget_seconds"],
        review=bool(design["review_rounds"]),
        review_max_responses=design["review_max_responses"],
        trace=True,
    )
    module = importlib.import_module("phase2.tasks.study_tasks")
    script = Path(module.__file__).read_bytes()
    env = read_env(env_path)
    rows = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(run_trial, args, cell, output, env, module, script) for cell in cells
        ]
        for future in as_completed(futures):
            row = future.result()
            rows.append(row)
            write_json(output / "results.json", rows)
            print(trial_dir(key(row)), row["status"], row["score_status"], flush=True)


def select(original, replacements, output):
    design_path = original / "design.json"
    design = load(design_path)
    retry_design = load(replacements / "design.json")
    if retry_design.get("original_design_sha256") != sha(design_path):
        raise ValueError("The replacement batch refers to a different original design")
    planned = [tuple(cell) for cell in design["cells"]]
    originals = {key(row): row for row in load(original / "results.json")}
    retries = {key(row): row for row in load(replacements / "results.json")}
    if set(originals) != set(planned) or set(retries) != {
        tuple(cell) for cell in retry_design["cells"]
    }:
        raise ValueError("Wait until both batches have a result for all planned cells")
    if any(cell not in originals or not eligible(originals[cell]) for cell in retries):
        raise ValueError("A replacement can only follow a recorded request transport error")
    if any(
        retry_design[name] != design[name]
        for name in (
            "source_sha256",
            "model",
            "provider",
            "actor_image_id",
            "scorer_image_id",
            "score_seed",
            "max_responses",
            "review_max_responses",
            "max_tokens_per_response",
            "time_budget_seconds",
            "review_rounds",
            "temperature",
            "reasoning",
            "suite",
        )
    ):
        raise ValueError("The replacement design differs in the study configuration")
    output.mkdir(parents=True)
    selected, decisions = [], []
    for cell in planned:
        row = originals[cell]
        path = original / trial_dir(cell)
        if cell in retries:
            replacement = retries[cell]
            recovered = replacement["status"] != "pipeline_error" and replacement["score"].get(
                "function_pass"
            ) in (True, False)
            decisions.append(
                {
                    "cell": cell,
                    "recovered": recovered,
                    "original_status": row["status"],
                    "replacement_status": replacement["status"],
                    "original_observed_tokens": row["metrics"]["total_tokens"],
                    "replacement_observed_tokens": replacement["metrics"]["total_tokens"],
                }
            )
            if recovered:
                row = replacement
                path = replacements / trial_dir(cell)
        (output / trial_dir(cell)).symlink_to(
            os.path.relpath(path, output), target_is_directory=True
        )
        selected.append(row)
    write_json(output / "design.json", design)
    write_json(output / "results.json", selected)
    write_json(output / "selection.json", {"replacement_decisions": decisions})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="action", required=True)
    rerun = modes.add_parser("retry")
    rerun.add_argument("original", type=Path)
    rerun.add_argument("env_file", type=Path)
    rerun.add_argument("out", type=Path)
    rerun.add_argument("--workers", type=int, choices=range(1, 5), default=2)
    choose = modes.add_parser("select")
    choose.add_argument("original", type=Path)
    choose.add_argument("replacements", type=Path)
    choose.add_argument("out", type=Path)
    args = parser.parse_args()
    if args.action == "retry":
        retry(args.original.resolve(), args.out.resolve(), args.env_file.resolve(), args.workers)
    else:
        select(args.original.resolve(), args.replacements.resolve(), args.out.resolve())


if __name__ == "__main__":
    main()
