"""Run a preregistered, randomized paired matrix with immutable per-job artifacts."""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import replace
from pathlib import Path

import yaml

from harnesslab.benchmark_runner import run_benchmark_experiment
from harnesslab.config import load_benchmark_experiment
from harnesslab.reproducibility import canonical_sha256, file_sha256, runtime_metadata
from harnesslab.study import validate_study_progress

ROOT = Path(__file__).resolve().parents[1]
ARMS = {
    "default": {"mode": "none"},
    "generic_retry": {"mode": "retry"},
    "rubric_transcript": {"mode": "rubric"},
    "rubric_evidence": {"mode": "rubric", "evidence_tools": True},
}


def source_hashes() -> dict[str, str]:
    paths = [ROOT / "uv.lock", ROOT / "pyproject.toml"]
    for directory, pattern in [("src", "*.py"), ("benchmarks/rubric-v1", "*.yaml")]:
        paths.extend((ROOT / directory).rglob(pattern))
    paths.extend(
        [
            Path(__file__),
            ROOT / "scripts/build_rubric_suite.py",
            ROOT / "scripts/analyze_rubric_matrix.py",
            ROOT / "scripts/calibrate_rubric_grader.py",
            ROOT / "scripts/server/serve-qwen35-9b.sh",
            ROOT / "docs/rubric-study-20261025.md",
        ]
    )
    return {path.relative_to(ROOT).as_posix(): file_sha256(path) for path in sorted(paths)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=["dev", "holdout"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20261025)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--limit-jobs", type=int)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    hashes = source_hashes()
    configurations = {}
    for arm, treatment in ARMS.items():
        config = {
            "schema_version": "0.2",
            "experiment": {
                "name": f"qwen35-{args.split}-{arm.replace('_', '-')}",
                "repeats": 1,
                "seed": args.seed,
            },
            "harness": {
                "kind": "deepagents_default",
                "model": {
                    "name": "Qwen3.5-9B",
                    "base_url": args.base_url,
                    "api_key_env": None,
                    "temperature": 0.7,
                    "max_completion_tokens": 2048,
                    "max_retries": 0,
                    "request_timeout_seconds": 90,
                    "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
                },
                "verification": {
                    **treatment,
                    "max_iterations": 3,
                    "total_model_call_limit": 24,
                    "total_tool_call_limit": 60,
                    "grader_call_limit": 12,
                },
            },
            "catalog": str(ROOT / f"benchmarks/rubric-v1/{args.split}.yaml"),
            "output": {"directory": str(args.output / "runs")},
        }
        path = args.output / f"{arm}.yaml"
        encoded = yaml.safe_dump(config, sort_keys=False)
        if path.exists() and path.read_text() != encoded:
            raise SystemExit(f"refusing to modify a frozen config: {path}")
        if not path.exists():
            path.write_text(encoded)
        configurations[arm] = load_benchmark_experiment(path)
    jobs = []
    cases = configurations["default"].cases
    rng = random.Random(args.seed)
    blocks = [(case.public.task_ref, repeat) for case in cases for repeat in range(args.repeats)]
    rng.shuffle(blocks)
    for task_ref, repeat in blocks:
        arms = list(ARMS)
        rng.shuffle(arms)
        for arm in arms:
            jobs.append(
                {"arm": arm, "task_ref": task_ref, "repeat": repeat, "seed": args.seed + repeat}
            )
    manifest = {
        "protocol": "rubric-v1",
        "split": args.split,
        "repeats": args.repeats,
        "source_hashes": hashes,
        "schedule": jobs,
        "model": "Qwen3.5-9B",
        "model_revision": "c202236235762e1c871ad0ccb60c8ee5ba337b9a",
        "sampling": {"temperature": 0.7, "thinking": False},
        "budget_matching": "equal ceilings; realized compute differs and is reported",
        "claim_boundary": ("synthetic instances in 3 task families; not independent task families"),
        "runtime": runtime_metadata(),
        "arm_config_hashes": {arm: file_sha256(args.output / f"{arm}.yaml") for arm in ARMS},
        "arm_harness_settings": {
            arm: loaded.config.harness.model_dump(mode="json")
            for arm, loaded in configurations.items()
        },
    }
    manifest_path = args.output / "study-manifest.json"
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text())
        if previous["source_hashes"] != hashes or previous["schedule"] != jobs:
            raise SystemExit("source or schedule changed; start a NEW study output directory")
    else:
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    progress_path = args.output / "progress.jsonl"
    previous_jobs = (
        []
        if not progress_path.exists()
        else [json.loads(line) for line in progress_path.read_text().splitlines() if line]
    )
    validate_study_progress(manifest, previous_jobs)
    done = {entry["job_key"] for entry in previous_jobs}
    completed_now = 0
    for index, job in enumerate(jobs):
        key = canonical_sha256(job)
        if key in done:
            continue
        loaded = configurations[job["arm"]]
        config = loaded.config.model_copy(deep=True)
        config.experiment.seed = job["seed"]
        case = next(case for case in cases if case.public.task_ref == job["task_ref"])
        selected = replace(loaded, config=config, cases=(case,))
        result = run_benchmark_experiment(selected, repeat_offset=job["repeat"])
        record = {
            **job,
            "job_key": key,
            "index": index,
            "total": len(jobs),
            "artifact_directory": str(result.output_directory),
            "success": result.runs[0].success,
            "status": result.runs[0].status,
        }
        with progress_path.open("a") as handle:
            handle.write(json.dumps(record) + "\n")
        print(json.dumps(record), flush=True)
        completed_now += 1
        if args.limit_jobs is not None and completed_now >= args.limit_jobs:
            break
    print(
        json.dumps(
            {
                "finished": len(done) + completed_now == len(jobs),
                "completed": len(done) + completed_now,
                "total": len(jobs),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
