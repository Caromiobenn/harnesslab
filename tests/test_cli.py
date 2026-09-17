import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_module_cli_runs_without_provider_credentials(tmp_path: Path) -> None:
    environment = os.environ.copy()
    for variable in (
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
    ):
        environment.pop(variable, None)

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "harnesslab",
            "run",
            "configs/smoke.yaml",
            "--output-dir",
            str(tmp_path),
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    summary = json.loads(completed.stdout)
    assert summary["successful_runs"] == 1
    assert summary["execution_errors"] == 0
    assert Path(summary["artifact_directory"]).is_dir()


def test_cli_can_fail_ci_on_validation_failure(tmp_path: Path) -> None:
    task_path = tmp_path / "task.yaml"
    task = yaml.safe_load(
        (PROJECT_ROOT / "tasks/smoke/sum_numbers.yaml").read_text(encoding="utf-8")
    )
    task["expected"] = {"sum": 999}
    task_path.write_text(yaml.safe_dump(task, sort_keys=False), encoding="utf-8")

    config_path = tmp_path / "config.yaml"
    config = yaml.safe_load((PROJECT_ROOT / "configs/smoke.yaml").read_text(encoding="utf-8"))
    config["tasks"] = ["task.yaml"]
    config["output"]["directory"] = "runs"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "harnesslab",
            "run",
            str(config_path),
            "--fail-on-validation",
        ],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1
    summary = json.loads(completed.stdout)
    assert summary["validation_failures"] == 1
    assert summary["execution_errors"] == 0
