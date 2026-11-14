"""One immutable plan, fresh sandboxes, official verification, and exact-ID cleanup."""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from harnesslab.coding.config import CodingConfig, model_settings, save_json, thinking_body


def task_plan(root: Path, config: CodingConfig, task: str) -> dict:
    from benchmark_next_environment import source_fingerprint
    from harbor.models.task.config import TaskConfig

    lock = json.loads((root / "configs/coding-tasks.lock.json").read_text())
    if lock["revision"] != config.revision or task not in lock["tasks"]:
        raise ValueError("Task is outside the pinned acceptance set")
    dataset = root / "artifacts/datasets" / config.benchmark
    folder = dataset / "tasks" / task
    actual = {p.relative_to(dataset).as_posix() for p in folder.rglob("*") if p.is_file()}
    expected = {name for name in lock["files"] if name.startswith(f"tasks/{task}/")}
    if actual != expected:
        raise ValueError(f"Task file set changed: {task}")
    for name in expected:
        if hashlib.sha256((dataset / name).read_bytes()).hexdigest() != lock["files"][name]:
            raise ValueError(f"Task content changed: {name}")
    spec = TaskConfig.model_validate_toml((folder / "task.toml").read_text())
    fingerprint = source_fingerprint(folder / "environment", spec.environment)
    mapping = json.loads((root / "configs/benchmark-images-next.json").read_text())["environments"]
    selected = mapping[fingerprint]
    return {
        "task": task,
        "path": str(folder),
        "source_fingerprint": fingerprint,
        "template_id": selected["template_id"],
        "agent_seconds": spec.agent.timeout_sec,
        "verifier_seconds": spec.verifier.timeout_sec,
        "build_seconds": spec.environment.build_timeout_sec,
        "environment": spec.environment.model_dump(mode="json"),
    }


def job_config(root: Path, config: CodingConfig, row: dict, group: str, name: str) -> dict:
    from harbor.models.job.config import JobConfig

    native = False
    environment_import = "benchmark_next_environment:BenchmarkAliyunEnvironment"
    if config.prerequisites_manifest:
        entry = json.loads((root / config.prerequisites_manifest).read_text())["tasks"][row["task"]]
        profile = entry.get("runtime_profile", "pilot")
        if profile not in ("pilot", "native"):
            raise ValueError("Unknown task runtime profile: " + profile)
        native = profile == "native"
        environment_import = (
            "harnesslab.coding.native_environment:NativeStudyEnvironment"
            if native
            else "harnesslab.coding.environment:StudyEnvironment"
        )
    if group == "empty":
        agent = {
            "import_path": "harnesslab.coding.controls:"
            + ("NativeEmptyControl" if native else "EmptyControl")
        }
        if native:
            agent["kwargs"] = {"network_mode": config.network_mode}
    elif group == "oracle":
        agent = {
            "import_path": "harnesslab.coding.controls:"
            + ("NativeOracleControl" if native else "OracleControl"),
            "kwargs": {
                "task_dir": row["path"],
                "agent_timeout_sec": row["agent_seconds"],
            },
        }
        if native:
            agent["kwargs"]["network_mode"] = config.network_mode
    else:
        model = model_settings(root, require_key=False)["model"]
        agent = {
            "import_path": "harnesslab.coding.agents:"
            + ("MiniCodingAgent" if group == "mini" else "DeepAgentsCodingAgent"),
            "model_name": "deepseek/" + model,
            "kwargs": {"experiment": config.model_dump()},
        }
        if group == "mini":
            agent["kwargs"]["wall_time_seconds"] = row["agent_seconds"]
        else:
            agent["kwargs"]["group"] = group
    data = {
        "job_name": name,
        "jobs_dir": str(root / "artifacts/coding/jobs"),
        "n_attempts": 1,
        "n_concurrent_trials": 1,
        "retry": {"max_retries": 0},
        "tasks": [{"path": row["path"]}],
        "agents": [agent],
        "environment": {
            "import_path": environment_import,
            "delete": True,
            "kwargs": {
                "profile_file": ".env.sandbox",
                "image_map": "configs/benchmark-images-next.json",
                "sandbox_timeout_secs": int(
                    row["agent_seconds"] + row["verifier_seconds"] + row["build_seconds"] + 1200
                ),
                **(
                    {"prerequisites_manifest": config.prerequisites_manifest}
                    if config.prerequisites_manifest
                    else {}
                ),
            },
        },
        "verifier": {"disable": False},
    }
    JobConfig.model_validate(data)
    return data


def preflight_environment(root: Path, config: CodingConfig, row: dict) -> None:
    """Construct the selected adapter without creating a cloud instance."""
    from benchmark_next_environment import BenchmarkAliyunEnvironment
    from harbor.models.task.config import EnvironmentConfig
    from harbor.models.trial.paths import TrialPaths

    environment = job_config(root, config, row, "empty", "preflight")["environment"]
    adapter = BenchmarkAliyunEnvironment
    if environment["import_path"].endswith(":NativeStudyEnvironment"):
        from harnesslab.coding.native_environment import NativeStudyEnvironment

        adapter = NativeStudyEnvironment
    elif config.prerequisites_manifest:
        from harnesslab.coding.environment import StudyEnvironment

        adapter = StudyEnvironment
    elif config.network_mode == "offline":
        raise ValueError("Offline trials require the common public-prerequisite environment")
    adapter(
        environment_dir=Path(row["path"]) / "environment",
        environment_name=row["task"],
        session_id="harnesslab-preflight",
        trial_paths=TrialPaths(trial_dir=root / "artifacts/coding/preflight" / row["task"]),
        task_env_config=EnvironmentConfig.model_validate(row["environment"]),
        **environment["kwargs"],
    )


def execute_stage(
    root: Path,
    folder: Path,
    row: dict,
    group: str,
    config: CodingConfig,
    batch: str,
    repeat: int,
    resume: bool,
) -> dict:
    from benchmark_next_cleanup import cleanup_run

    name = f"{batch}-{row['task']}-{group}-{repeat}"
    config_path = folder / f"{name}.config.json"
    outcome_path = folder / f"{name}.outcome.json"
    data = job_config(root, config, row, group, name)
    if config_path.exists():
        if not resume or json.loads(config_path.read_text()) != data:
            raise ValueError(f"Existing stage has a different plan or needs --resume: {name}")
        if outcome_path.exists():
            return json.loads(outcome_path.read_text())
        raise ValueError(f"Incomplete stage retained; use a new batch after inspection: {name}")
    save_json(config_path, data)
    env = dict(os.environ, BENCHMARK_NEXT_RUN=name, HARNESSLAB_ROOT=str(root))
    command = [sys.executable, "-m", "harnesslab.coding.cli", "child", str(config_path)]
    exit_code = None
    error = None
    cleanup = None
    try:
        with (folder / f"{name}.log").open("w") as stream:
            result = subprocess.run(
                command,
                cwd=root,
                env=env,
                stdout=stream,
                stderr=subprocess.STDOUT,
                timeout=int(
                    row["agent_seconds"] + row["verifier_seconds"] + 2 * row["build_seconds"] + 1800
                ),
            )
            exit_code = result.returncode
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        owned = set()
        for path in (root / "artifacts/coding/jobs" / name).glob("*/trial.log"):
            owned.update(re.findall(r"Created sandbox ([A-Za-z0-9_-]+) from", path.read_text()))
        cleanup = cleanup_run(root, name, profile_file=".env.sandbox", expected_ids=owned)
        save_json(folder / f"{name}.cleanup.json", cleanup)
    results = list((root / "artifacts/coding/jobs" / name).glob("*/result.json"))
    result = json.loads(results[0].read_text()) if len(results) == 1 else {}
    exception = result.get("exception_info")
    rewards = (result.get("verifier_result") or {}).get("rewards") or {}
    reward = rewards.get("reward")
    budget_stop = (exception or {}).get("exception_type") == "AgentTimeoutError"
    review = ((result.get("agent_result") or {}).get("metadata") or {}).get("review_outcome")
    review_error = bool(review and review.get("status") in ("grader_error", "failed"))
    pipeline_ok = (
        exit_code == 0
        and error is None
        and reward is not None
        and (exception is None or budget_stop)
        and not review_error
        and cleanup["verified"]
    )
    outcome = {
        "task": row["task"],
        "group": group,
        "network_mode": config.network_mode,
        "repeat": repeat,
        "job_name": name,
        "pipeline_ok": pipeline_ok,
        "reward": reward,
        "exception": exception,
        "controller_error": error,
        "exit_code": exit_code,
        "cleanup_verified": cleanup["verified"],
        "review_error": review_error,
        "trial": str(results[0].parent) if len(results) == 1 else None,
        "agent_result": result.get("agent_result"),
    }
    save_json(outcome_path, outcome)
    if len(results) == 1 and group not in ("empty", "oracle"):
        from harnesslab.coding.metrics import trial_metrics

        outcome["metrics"] = trial_metrics(results[0].parent, result)
        if config.langsmith_tracing and group != "mini":
            from harnesslab.coding.observability import publish_trial

            outcome["langsmith"] = publish_trial(root, results[0].parent, outcome)
        save_json(outcome_path, outcome)
    print(
        json.dumps({key: outcome[key] for key in ("task", "group", "reward", "pipeline_ok")}),
        flush=True,
    )
    return outcome


def run_batch(
    root: Path,
    config: CodingConfig,
    batch: str,
    resume: bool = False,
    reuse_manifest: Path | None = None,
    controls_manifest: Path | None = None,
) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", batch):
        raise ValueError("Use a short alphanumeric batch name")
    model = model_settings(root)
    folder = root / "artifacts/coding" / batch
    folder.mkdir(parents=True, exist_ok=True)
    rows = [task_plan(root, config, name) for name in config.tasks]
    for row in rows:
        preflight_environment(root, config, row)
    hashes = {}
    for path in sorted((root / "src/harnesslab/coding").glob("*.py")):
        hashes[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    for path in sorted((root / "vendor/hongkong").glob("*.py")):
        hashes[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    for relative in (
        "uv.lock",
        "configs/coding-tasks.lock.json",
        "vendor/hongkong/provenance.json",
        "configs/benchmark-images-next.json",
        "configs/benchmark-runtime-next.json",
    ):
        hashes[relative] = hashlib.sha256((root / relative).read_bytes()).hexdigest()
    if config.prerequisites_manifest:
        path = root / config.prerequisites_manifest
        hashes[config.prerequisites_manifest] = hashlib.sha256(path.read_bytes()).hexdigest()
    plan = {
        "configuration": config.model_dump(),
        "tasks": rows,
        "source_hashes": hashes,
        "model": model["model"],
        "base_url": model["base_url"],
        "api_style": model["api_style"],
        "thinking_body": thinking_body(config, model),
    }
    references = {}
    if reuse_manifest is not None:
        from harnesslab.coding.reuse import digest, load_reuse

        references = load_reuse(reuse_manifest, plan)
        plan["reuse_manifest"] = {"path": str(reuse_manifest), "sha256": digest(reuse_manifest)}
    plan_path = folder / "plan.json"
    control_references = {}
    if controls_manifest is not None:
        from harnesslab.coding.control_reuse import load_control_reuse
        from harnesslab.coding.reuse import digest

        control_references = load_control_reuse(root, controls_manifest, plan)
        if control_references.keys() & references.keys():
            raise ValueError("A control is supplied by two continuation manifests")
        plan["controls_manifest"] = {
            "path": str(controls_manifest),
            "sha256": digest(controls_manifest),
        }
    if plan_path.exists() and (not resume or json.loads(plan_path.read_text()) != plan):
        raise ValueError("Batch plan is immutable; use a new batch for code/config changes")
    save_json(plan_path, plan)
    outcomes = []

    def stage(row, group, repeat):
        key = config.network_mode, row["task"], group, repeat
        if key in control_references:
            from harnesslab.coding.control_reuse import save_reused_control

            return save_reused_control(folder, batch, control_references[key], resume)
        if key in references:
            from harnesslab.coding.reuse import save_reused

            return save_reused(folder, batch, references[key], resume)
        return execute_stage(root, folder, row, group, config, batch, repeat, resume)

    def run_task(row):
        records = []
        for control, expected in (("empty", 0), ("oracle", 1)):
            outcome = stage(row, control, 0)
            records.append(outcome)
            if not outcome["pipeline_ok"] or outcome["reward"] != expected:
                return records
        for repeat in range(config.repeats):
            for group in config.groups:
                records.append(stage(row, group, repeat))
        return records

    with concurrent.futures.ThreadPoolExecutor(max_workers=config.concurrency) as pool:
        futures = {pool.submit(run_task, row): row["task"] for row in rows}
        for future in concurrent.futures.as_completed(futures):
            try:
                outcomes.extend(future.result())
            except Exception as exc:
                outcomes.append(
                    {
                        "task": futures[future],
                        "pipeline_ok": False,
                        "controller_error": f"{type(exc).__name__}: {exc}",
                    }
                )
            save_json(folder / "progress.json", outcomes)
    model_runs = [row for row in outcomes if row.get("group") in config.groups]
    expected_runs = len(config.tasks) * len(config.groups) * config.repeats
    summary = {
        "expected_model_runs": expected_runs,
        "completed_model_runs": len(model_runs),
        "reused_model_runs": sum("reuse" in row for row in model_runs),
        "integration_passed": len(model_runs) == expected_runs
        and all(row["pipeline_ok"] for row in outcomes),
        "groups": {
            group: {
                "valid_runs": sum(
                    row["pipeline_ok"] for row in model_runs if row["group"] == group
                ),
                "successes": sum(
                    row["pipeline_ok"] and row["reward"] == 1
                    for row in model_runs
                    if row["group"] == group
                ),
            }
            for group in config.groups
        },
        "outcomes": outcomes,
    }
    save_json(folder / "summary.json", summary)
    return summary
