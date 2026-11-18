"""Replay disclosed checks against saved Phase 2 files without calling a model."""

import argparse
import concurrent.futures
import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "phase2" / "artifacts" / "accepted-matrix-20261118"
SCORE = ROOT / "phase2" / "tasks" / "study_tasks.py"
DELIVERABLES = {"solution", "solution.c"}


def sha(value):
    return hashlib.sha256(value).hexdigest()


def load(path):
    return json.loads(path.read_bytes())


def executable(event):
    entry = event["files"].get("solution")
    return entry is not None and entry[1] is True


def verify(event, directory):
    """Check content and executable flags against the corresponding snapshot."""
    manifest = event["files"]
    artifact = event["digest"]
    if sha(json.dumps(manifest, sort_keys=True).encode()) != artifact:
        raise ValueError(f"Snapshot manifest digest differs: {directory.name}")
    snapshot = directory / "snapshots" / artifact
    for name, entry in manifest.items():
        if name not in DELIVERABLES:
            raise ValueError(f"Unexpected manifest file: {name}")
        if entry is not None:
            expected, executable = entry
            path = snapshot / name
            if path.is_symlink() or sha(path.read_bytes()) != expected:
                raise ValueError(f"Snapshot content digest differs: {path}")
            if bool(path.stat().st_mode & 0o111) is not executable:
                raise ValueError(f"Snapshot mode differs: {path}")
    return snapshot


def replay(snapshot, task, requirement, image, source):
    command = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--network",
        "none",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,exec,nosuid,nodev,size=128m",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "96",
        "--memory",
        "640m",
        "--cpus",
        "1",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--env",
        "HOME=/tmp",
        "--mount",
        f"type=bind,src={snapshot},dst=/submission,ro",
        image,
        "python3",
        "-",
        "public-check",
        "/submission",
        task,
        requirement,
    ]
    raw = subprocess.check_output(command, input=source, timeout=45)
    result = json.loads(raw)
    if (
        type(result.get("trigger_review")) is not bool
        or type(result.get("checks", {}).get("public_example")) is not bool
        or type(result.get("checks", {}).get("submitted_requirements")) is not bool
    ):
        raise ValueError(f"Public-check output missing: {snapshot}")
    return result


def point(event, evaluations):
    if event is None:
        return None
    observation = evaluations.get(event["digest"])
    hidden = event["score"]
    return {
        **{key: event.get(key) for key in ("label", "responses", "tokens", "seconds", "digest")},
        "executable_present": executable(event),
        "public_example_pass": bool(observation and observation["checks"]["public_example"]),
        "public_requirements_pass": bool(
            observation and observation["checks"]["submitted_requirements"]
        ),
        "public_gate_pass": bool(observation and not observation["trigger_review"]),
        "hidden_qualified_as_recorded": hidden["qualified"],
        "hidden_function_pass_as_recorded": hidden["function_pass"],
        "hidden_passed_as_recorded": hidden["function_checks"]["passed"],
        "hidden_total_as_recorded": hidden["function_checks"]["total"],
    }


def summarize_case(directory, result, events, evaluations):
    checkpoints = [point(event, evaluations) for event in events]

    def first(field):
        return next((row for row in checkpoints if row[field]), None)

    return {
        "case": directory.name,
        **{key: result[key] for key in ("task", "requirement", "toolchain", "repeat", "status")},
        "timeline_sha256": sha((directory / "timeline.json").read_bytes()),
        "first_executable": first("executable_present"),
        "first_public_example_pass": first("public_example_pass"),
        "first_public_gate_pass": first("public_gate_pass"),
        "first_hidden_qualified_as_recorded": first("hidden_qualified_as_recorded"),
        "final": checkpoints[-1],
        "replayed_public_checks": evaluations,
    }


def analyze(matrix, scorer, workers):
    design_bytes = (matrix / "design.json").read_bytes()
    design = json.loads(design_bytes)
    source = scorer.read_bytes()
    source_sha = sha(source)
    expected_sha = design["source_sha256"]["phase2/tasks/study_tasks.py"]
    if source_sha != expected_sha:
        raise ValueError("The replay scorer bytes differ from the frozen Phase 2 design")
    image = design["scorer_image_id"]
    cases, paths, jobs = [], {}, {}
    for task, requirement, toolchain, repeat in sorted(design["cells"]):
        directory = matrix / f"{task}--{requirement}--{toolchain}--r{repeat}"
        result = load(directory / "result.json")
        events = load(directory / "timeline.json")
        if any(event["label"] == "first_candidate" for event in events):
            continue
        if events[-1]["label"] != "final" or result["score"] != events[-1]["score"]:
            raise ValueError(f"Final timeline and result differ: {directory}")
        cases.append((directory, result, events))
        for event in events:
            key = directory.name, event["digest"]
            if key not in paths:
                paths[key] = verify(event, directory)
                if executable(event):
                    jobs[key] = (paths[key], task, requirement, image, source)

    evaluations = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(replay, *job): key for key, job in jobs.items()}
        for future in concurrent.futures.as_completed(futures):
            case, artifact = futures[future]
            evaluations.setdefault(case, {})[artifact] = future.result()

    rows = [
        summarize_case(directory, result, events, evaluations.get(directory.name, {}))
        for directory, result, events in cases
    ]
    failed = [row for row in rows if not row["final"]["hidden_qualified_as_recorded"]]

    def milestones(field):
        observed = [row[field] for row in rows if row[field] is not None]
        return {
            "ever": len(observed),
            "hidden_qualified_when_first_passed_as_recorded": sum(
                row["hidden_qualified_as_recorded"] for row in observed
            ),
            "final_hidden_failed_among_ever_public_passed": sum(
                row[field] is not None for row in failed
            ),
        }

    return {
        "matrix": matrix.name,
        "design_sha256": sha(design_bytes),
        "score_sha256": source_sha,
        "scorer_image_id": image,
        "score_network": "none",
        "model_calls": 0,
        "matrix_cells": len(design["cells"]),
        "selected_no_first_candidate": len(rows),
        "unique_snapshot_manifests_verified": len(paths),
        "unique_runnable_snapshots_replayed": len(jobs),
        "first_public_example": milestones("first_public_example_pass"),
        "first_public_gate": milestones("first_public_gate_pass"),
        "final": {
            "executable_present": sum(row["final"]["executable_present"] for row in rows),
            "public_example_pass": sum(row["final"]["public_example_pass"] for row in rows),
            "public_gate_pass": sum(row["final"]["public_gate_pass"] for row in rows),
            "hidden_qualified_as_recorded": len(rows) - len(failed),
            "hidden_failed_with_public_example_pass": sum(
                row["final"]["public_example_pass"] for row in failed
            ),
            "hidden_failed_with_public_gate_pass": sum(
                row["final"]["public_gate_pass"] for row in failed
            ),
        },
        "cases": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=MATRIX)
    parser.add_argument("--scorer", type=Path, default=SCORE)
    parser.add_argument("--workers", type=int, choices=(1, 2), default=2)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = analyze(args.matrix.resolve(), args.scorer.resolve(), args.workers)
    args.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
