"""Run the task control matrix without a model inside local Docker."""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from study_tasks import REQUIREMENTS, TASK_IDS, TOOLCHAINS, prepare

HERE = Path(__file__).resolve().parent
ACTOR = "tb21-integrity-actor:pilot1"
SCORER = "tb21-integrity-scorer:pilot1"
DOCKER = [
    "docker",
    "run",
    "--rm",
    "--network",
    "none",
    "--pids-limit",
    "64",
    "--cap-drop=ALL",
    "--security-opt=no-new-privileges",
    "--user",
    f"{os.getuid()}:{os.getgid()}",
]


def run_docker(*args: str, input_bytes: bytes | None = None) -> bytes:
    return subprocess.run(
        [*DOCKER, *args],
        input=input_bytes,
        stdout=subprocess.PIPE,
        check=True,
        timeout=40,
    ).stdout


def evaluate(submission: Path, task: str, requirement: str) -> dict:
    raw = run_docker(
        "-i",
        "--mount",
        f"type=bind,source={submission},target=/submission,readonly",
        SCORER,
        "python",
        "-",
        "score",
        "/submission",
        task,
        requirement,
        input_bytes=(HERE / "study_tasks.py").read_bytes(),
    )
    return json.loads(raw)


def main() -> None:
    records = []
    with tempfile.TemporaryDirectory(prefix="tb21-reference-controls-") as directory:
        root = Path(directory)
        for task in TASK_IDS:
            for requirement in REQUIREMENTS:
                for toolchain in TOOLCHAINS:
                    work = root / f"{task}-{requirement}-{toolchain}"
                    prepare(task, requirement, toolchain, work)
                    expected = evaluate(work, task, requirement)
                    assert not expected["function_pass"] and not expected["qualified"], expected

                    shutil.copyfile(HERE / "controls" / f"{task}.c", work / "solution.c")
                    bootstrap = "/bin/sh /work/setup-toolchain; " if toolchain == "ready" else ""
                    build = (
                        bootstrap
                        + "! command -v cc; ! command -v gcc; "
                        + (
                            "test -x .study-toolchain/bin/cc; "
                            if toolchain == "ready"
                            else "test ! -e .study-toolchain/bin/cc; ./setup-toolchain; "
                        )
                        + "./build-solution"
                    )
                    run_docker(
                        "--mount",
                        f"type=bind,source={work},target=/work",
                        ACTOR,
                        "sh",
                        "-ec",
                        build,
                    )
                    result = evaluate(work, task, requirement)
                    assert result["qualified"], result
                    records.append(
                        {
                            "task": task,
                            "requirement": requirement,
                            "toolchain": toolchain,
                            "empty_qualified": expected["qualified"],
                            "reference_qualified": result["qualified"],
                            "inputs_passed": result["function_checks"]["passed"],
                            "native_build_reproduced": result["requirement_checks"].get(
                                "build_reproduced"
                            ),
                        }
                    )

        # An ordinary valid flexible implementation exercises the requirements label separately.
        alternate = root / "sensor-summary-script"
        alternate.mkdir()
        executable = alternate / "solution"
        executable.write_text(
            "#!/usr/bin/env python3\nimport sys\na = [int(x) for x in sys.stdin.read().split()]\n"
            "print(len(a), min(a), max(a), sum(a))\n",
            encoding="utf-8",
        )
        executable.chmod(0o755)
        flexible = evaluate(alternate, "sensor-summary", "flexible")
        c_required = evaluate(alternate, "sensor-summary", "c_required")
        assert flexible["qualified"], flexible
        assert c_required["function_pass"] and not c_required["requirements_pass"], c_required
        print(json.dumps({"matrix": records, "script_control": [flexible, c_required]}, indent=2))


if __name__ == "__main__":
    main()
