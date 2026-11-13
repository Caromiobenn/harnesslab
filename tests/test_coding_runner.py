"""Check frozen task integrity, result classification, controls, resume, and cleanup."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("harbor")

from harnesslab.coding import config as configuration
from harnesslab.coding import runner
from harnesslab.coding.config import CodingConfig, model_settings, save_json, thinking_body


@pytest.fixture
def project(tmp_path, monkeypatch):
    config = CodingConfig(
        benchmark="terminal-bench-2.1",
        revision="fixture",
        tasks=["task"],
        purpose="offline integration contract",
    )
    root = tmp_path
    (root / ".env").write_text("DEEPSEEK_API_KEY=fixture-secret\n")
    folder = root / "artifacts/datasets/terminal-bench-2.1/tasks/task"
    (folder / "environment").mkdir(parents=True)
    (folder / "task.toml").write_text(
        'version = "1.0"\n[agent]\ntimeout_sec = 10\n[verifier]\ntimeout_sec = 10\n'
        "[environment]\ncpus = 1\nbuild_timeout_sec = 60\n"
    )
    (folder / "environment/Dockerfile").write_text("FROM python:3.12\nWORKDIR /app\n")
    files = {
        p.relative_to(root / "artifacts/datasets/terminal-bench-2.1").as_posix(): hashlib.sha256(
            p.read_bytes()
        ).hexdigest()
        for p in folder.rglob("*")
        if p.is_file()
    }
    save_json(
        root / "configs/coding-tasks.lock.json",
        {"revision": "fixture", "tasks": ["task"], "files": files},
    )
    save_json(
        root / "configs/benchmark-images-next.json",
        {"environments": {"fingerprint": {"template_id": "fixture-template"}}},
    )
    save_json(root / "configs/benchmark-runtime-next.json", {})
    save_json(root / "configs/coding-tb21.json", config.model_dump())
    save_json(root / "vendor/hongkong/provenance.json", {})
    (root / "uv.lock").write_text("fixture-lock")
    monkeypatch.setitem(
        sys.modules,
        "benchmark_next_environment",
        SimpleNamespace(
            source_fingerprint=lambda *args: "fingerprint",
            BenchmarkAliyunEnvironment=lambda **kwargs: SimpleNamespace(**kwargs),
        ),
    )
    cleanup_calls = []

    def cleanup(*args, **kwargs):
        cleanup_calls.append((args, kwargs))
        return {"verified": True}

    monkeypatch.setitem(sys.modules, "benchmark_next_cleanup", SimpleNamespace(cleanup_run=cleanup))
    return root, config, cleanup_calls


def test_task_hashes_reject_changed_content_and_extra_files(project):
    root, config, _ = project
    row = runner.task_plan(root, config, "task")
    assert row["template_id"] == "fixture-template"
    runner.preflight_environment(root, config, row)
    path = Path(row["path"]) / "task.toml"
    original = path.read_bytes()
    path.write_bytes(original + b"\n")
    with pytest.raises(ValueError, match="content changed"):
        runner.task_plan(root, config, "task")
    path.write_bytes(original)
    (path.parent / "extra").write_text("added")
    with pytest.raises(ValueError, match="file set changed"):
        runner.task_plan(root, config, "task")


@pytest.mark.parametrize("group", ["empty", "oracle", "mini", "deepagents_default"])
def test_all_groups_keep_official_budgets_and_fresh_instances(project, group):
    root, config, _ = project
    row = runner.task_plan(root, config, "task")
    plan = runner.job_config(root, config, row, group, "fixture")
    assert plan["tasks"] == [{"path": row["path"]}]
    assert plan["environment"]["delete"] is True
    assert plan["verifier"]["disable"] is False
    assert plan["retry"]["max_retries"] == 0
    assert "fixture-secret" not in json.dumps(plan)


@pytest.mark.parametrize(
    "reward,exception,review_status,valid",
    [
        (0, None, None, True),
        (1, None, None, True),
        (0, "AgentTimeoutError", None, True),
        (None, "RuntimeError", None, False),
        (1, "VerifierTimeoutError", None, False),
        (1, None, "grader_error", False),
        (0, None, "max_iterations_reached", True),
    ],
)
def test_official_verdict_and_infrastructure_errors_remain_distinct(
    project, monkeypatch, reward, exception, review_status, valid
):
    root, config, cleanups = project
    row = runner.task_plan(root, config, "task")
    folder = root / "artifacts/coding/test"
    name = "test-task-mini-0"

    def child(*args, **kwargs):
        trial = root / "artifacts/coding/jobs" / name / "trial"
        save_json(
            trial / "result.json",
            {
                "verifier_result": {"rewards": {"reward": reward}},
                "exception_info": {"exception_type": exception} if exception else None,
                "agent_result": {"metadata": {"review_outcome": {"status": review_status}}},
            },
        )
        (trial / "trial.log").write_text("Created sandbox owned-id from template\n")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runner.subprocess, "run", child)
    result = runner.execute_stage(root, folder, row, "mini", config, "test", 0, False)
    assert result["pipeline_ok"] is valid
    assert result["reward"] == reward
    assert cleanups[0][1]["expected_ids"] == {"owned-id"}
    resumed = runner.execute_stage(root, folder, row, "mini", config, "test", 0, True)
    assert resumed == result
    assert len(cleanups) == 1
    with pytest.raises(ValueError, match="needs --resume"):
        runner.execute_stage(root, folder, row, "mini", config, "test", 0, False)


def test_cleanup_still_runs_after_controller_timeout(project, monkeypatch):
    root, config, cleanups = project
    row = runner.task_plan(root, config, "task")

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("fixture-child", 1)

    monkeypatch.setattr(runner.subprocess, "run", timeout)
    result = runner.execute_stage(
        root, root / "artifacts/coding/test", row, "mini", config, "test", 0, False
    )
    assert not result["pipeline_ok"]
    assert "TimeoutExpired" in result["controller_error"]
    assert cleanups


def test_batch_stops_task_after_invalid_control_and_rejects_changed_resume(project, monkeypatch):
    root, config, _ = project
    calls = []

    def stage(root, folder, row, group, config, batch, repeat, resume):
        calls.append(group)
        return {"task": row["task"], "group": group, "pipeline_ok": True, "reward": 1}

    monkeypatch.setattr(runner, "execute_stage", stage)
    result = runner.run_batch(root, config, "fixture")
    assert calls == ["empty"]
    assert not result["integration_passed"]
    assert result["completed_model_runs"] == 0
    (root / "uv.lock").write_text("changed-dependencies")
    with pytest.raises(ValueError, match="immutable"):
        runner.run_batch(root, config, "fixture", resume=True)


def test_batch_keeps_unsuccessful_model_solve_as_valid_and_captures_stage_exception(
    project, monkeypatch
):
    root, config, _ = project

    def stage(root, folder, row, group, config, batch, repeat, resume):
        return {
            "task": row["task"],
            "group": group,
            "pipeline_ok": True,
            "reward": 1 if group == "oracle" else 0,
        }

    monkeypatch.setattr(runner, "execute_stage", stage)
    result = runner.run_batch(root, config, "valid")
    assert result["integration_passed"]
    assert result["groups"]["mini"] == {"valid_runs": 1, "successes": 0}

    def fail(*args, **kwargs):
        raise RuntimeError("controller failure")

    monkeypatch.setattr(runner, "execute_stage", fail)
    result = runner.run_batch(root, config, "error")
    assert not result["integration_passed"]
    assert "controller failure" in result["outcomes"][0]["controller_error"]


def test_runtime_paths_and_provider_configuration_are_project_local(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "environ", dict(os.environ))
    monkeypatch.setattr(sys, "path", list(sys.path))
    configuration.configure_runtime(tmp_path)
    assert configuration.project_root() == tmp_path
    assert os.environ["DATA_ENGINEERING_ROOT"] == str(tmp_path)
    assert os.environ["UV_CACHE_DIR"].startswith(str(tmp_path))
    with pytest.raises(ValueError, match="Fill DEEPSEEK_API_KEY"):
        model_settings(tmp_path)
    assert not model_settings(tmp_path, require_key=False)["api_key"]
    config = CodingConfig(benchmark="terminal-bench-2.1", revision="fixture", tasks=[], purpose="x")
    assert thinking_body(config, {"api_style": "aliyun"}) == {"enable_thinking": True}
    assert thinking_body(config, {"api_style": "deepseek"}) == {"thinking": {"type": "enabled"}}
    with pytest.raises(ValueError, match="API_STYLE"):
        thinking_body(config, {"api_style": "unknown"})


@pytest.mark.parametrize("command", ["doctor", "plan", "run"])
def test_cli_uses_project_profile_and_reports_real_result(project, monkeypatch, capsys, command):
    from harnesslab.coding import cli

    root, _, _ = project
    monkeypatch.setattr(os, "environ", dict(os.environ))
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setenv("HARNESSLAB_ROOT", str(root))
    monkeypatch.setitem(
        sys.modules,
        "sandbox_profile",
        SimpleNamespace(
            load_profile=lambda *args: SimpleNamespace(public_summary=lambda: {"region": "fixture"})
        ),
    )
    monkeypatch.setattr(
        runner, "run_batch", lambda *args: {"integration_passed": True, "outcomes": []}
    )
    argv = ["coding", command]
    if command == "run":
        argv += ["--batch", "fixture", "--groups", "mini", "--tasks", "task"]
    monkeypatch.setattr(sys, "argv", argv)
    if command == "run":
        with pytest.raises(SystemExit) as exit_info:
            cli.main()
        assert exit_info.value.code == 0
    else:
        cli.main()
    result = capsys.readouterr().out
    assert "fixture-secret" not in result
    assert json.loads(result)


def test_cli_rejects_task_outside_frozen_set(project, monkeypatch):
    from harnesslab.coding import cli

    root, _, _ = project
    monkeypatch.setattr(os, "environ", dict(os.environ))
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setenv("HARNESSLAB_ROOT", str(root))
    monkeypatch.setattr(sys, "argv", ["coding", "run", "--batch", "test", "--tasks", "outside"])
    with pytest.raises(SystemExit) as exit_info:
        cli.main()
    assert exit_info.value.code == 2


def test_batch_reuses_a_scored_zero_without_executing_its_model(project, monkeypatch):
    from harnesslab.coding.reuse import digest

    root, config, _ = project
    calls = []

    def stage(root, folder, row, group, config, batch, repeat, resume):
        calls.append(group)
        return {
            "task": row["task"],
            "group": group,
            "repeat": repeat,
            "network_mode": config.network_mode,
            "pipeline_ok": True,
            "reward": int(group not in ("empty", "mini")),
            "cleanup_verified": True,
            "job_name": batch + "-" + group,
            "trial": "/original/trial",
        }

    monkeypatch.setattr(runner, "execute_stage", stage)
    first = runner.run_batch(root, config, "original")
    plan_path = root / "artifacts/coding/original/plan.json"
    plan = json.loads(plan_path.read_text())
    original = next(row for row in first["outcomes"] if row["group"] == "mini")
    outcome_path = plan_path.parent / "mini.outcome.json"
    save_json(outcome_path, original)
    manifest_path = root / "reuse.json"
    save_json(
        manifest_path,
        {
            "target_source_hashes": plan["source_hashes"],
            "references": [
                {
                    "outcome_path": str(outcome_path),
                    "outcome_sha256": digest(outcome_path),
                    "plan_path": str(plan_path),
                    "plan_sha256": digest(plan_path),
                    "compatible_groups": ["mini"],
                    "reviewed_source_differences": {},
                    "compatibility_reason": "Identical actor and task protocol.",
                }
            ],
        },
    )
    calls.clear()
    result = runner.run_batch(root, config, "continuation", reuse_manifest=manifest_path)
    assert calls == ["empty", "oracle", "deepagents_default"]
    assert result["reused_model_runs"] == 1
    assert result["groups"]["mini"] == {"valid_runs": 1, "successes": 0}
    saved = json.loads(
        (root / "artifacts/coding/continuation/continuation-task-mini-0.outcome.json").read_text()
    )
    assert saved["job_name"] == original["job_name"]
    assert saved["reuse"]["source_sha256"] == digest(outcome_path)
