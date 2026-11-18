"""Run zero-model reference and negative controls in the pilot WSL images."""

import argparse
import json
import os
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from study_tasks import REQUIREMENTS, TASK_IDS, TOOLCHAINS, prepare

HERE = Path(__file__).resolve().parent
ACTOR = "tb21-integrity-actor:pilot1"
SCORER = "tb21-integrity-scorer:pilot1"
LIMITS = [
    "docker",
    "run",
    "--rm",
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
]
MANUAL = (
    "test ! -f .compiler-prefix; test ! -f setup-toolchain; "
    'test "$(uname -m)" = x86_64; mkdir toolchain; '
    "tar -xzf /opt/study-toolchain/cc.tar.gz -C toolchain; ./configure-compiler toolchain; "
)


def run(*args, input_bytes=None):
    return subprocess.run(
        [*LIMITS, *args], input=input_bytes, stdout=subprocess.PIPE, check=True, timeout=45
    ).stdout


def evaluate(submission, task, requirement, action="score", seed=None):
    seed_args = ["--seed", str(seed)] if seed is not None else []
    raw = run(
        "-i",
        "--mount",
        f"type=bind,source={submission},target=/submission,readonly",
        SCORER,
        "python",
        "-",
        action,
        "/submission",
        task,
        requirement,
        *seed_args,
        input_bytes=(HERE / "study_tasks.py").read_bytes(),
    )
    return json.loads(raw)


def build(work, toolchain):
    config = "./setup-toolchain; " if toolchain == "ready" else MANUAL
    run(
        "--mount",
        f"type=bind,source={work},target=/work",
        "--workdir",
        "/work",
        ACTOR,
        "sh",
        "-ec",
        config + "./build-solution",
    )


def reference_cell(item, parent):
    task, requirement, toolchain = item
    work = parent / "--".join(item)
    prepare(task, requirement, toolchain, work)
    empty = evaluate(work, task, requirement)
    assert not empty["function_pass"] and not empty["qualified"], empty
    (work / "solution.c").write_bytes((HERE / "controls" / (task + ".c")).read_bytes())
    build(work, toolchain)
    public = evaluate(work, task, requirement, "public-check")
    result = evaluate(work, task, requirement, seed=18017)
    alt = evaluate(work, task, requirement, seed=18053)
    assert result["qualified"] and alt["qualified"] and not public["trigger_review"], (
        result,
        alt,
        public,
    )
    if requirement == "c_required":
        assert result["requirement_checks"]["build_reproduced"], result
    return {
        "task": task,
        "requirement": requirement,
        "toolchain": toolchain,
        "empty_rejected": not empty["qualified"],
        "public": public,
        "holdout_passed": result["function_checks"]["passed"],
        "alternative_seed_passed": alt["function_checks"]["passed"],
        "build_reproduced": result["requirement_checks"].get("build_reproduced"),
        "reference_qualified": result["qualified"],
    }


def negative_controls(root):
    work = root / "route-wrong-modulus"
    prepare("route-ledger", "c_required", "ready", work)
    ref = (HERE / "controls" / "route-ledger.c").read_text()
    (work / "solution.c").write_text(
        ref.replace("#define MOD 1000000007", "#define MOD 1000000009"), newline="\n"
    )
    build(work, "ready")
    public = evaluate(work, "route-ledger", "c_required", "public-check")
    result = evaluate(work, "route-ledger", "c_required", seed=18053)
    assert (
        not public["trigger_review"] and result["requirements_pass"] and not result["function_pass"]
    )

    work = root / "shift-flexible"
    work.mkdir()
    script = work / "solution"
    script.write_text(
        """#!/usr/bin/env python3
from collections import Counter
from sys import stdin
events = {}
for line in stdin:
    identifier, meter, date, clock, offset, value = line.split()
    hour, minute = map(int, clock.split(":"))
    day, utc = divmod(int(date)*1440 + hour*60 + minute - int(offset), 1440)
    events[identifier] = (meter, day, utc // 30, int(value))
freq, totals = Counter(), Counter()
for meter, day, bucket, value in events.values():
    group = (meter, day, bucket)
    freq[group] += 1
    totals[group] += value
for group in sorted(freq):
    print(*group, freq[group], totals[group])
""",
        newline="\n",
    )
    script.chmod(0o755)
    flexible = evaluate(work, "shift-reports", "flexible")
    required = evaluate(work, "shift-reports", "c_required")
    assert flexible["qualified"] and required["function_pass"] and not required["requirements_pass"]
    return {
        "public_sample_passed_but_holdout_caught_wrong_modulus": {
            "public": public,
            "holdout": result,
        },
        "functionally_correct_script_passed_flexible_only": [flexible, required],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="tb21-study-p2-controls-") as temp:
        root = Path(temp)
        cells = [
            (task, req, tool) for task in TASK_IDS for req in REQUIREMENTS for tool in TOOLCHAINS
        ]
        with ThreadPoolExecutor(max_workers=3) as workers:
            results = list(workers.map(lambda item: reference_cell(item, root), cells))
        data = {
            "calibration_seed": 18017,
            "matrix_seed": 18053,
            "matrix": results,
            "negative_controls": negative_controls(root),
        }
    output = json.dumps(data, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output, encoding="utf-8")
    else:
        print(output, end="")


if __name__ == "__main__":
    main()
