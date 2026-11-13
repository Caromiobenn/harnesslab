"""Plan and run the six-task coding-agent integration matrix."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from harnesslab.coding.config import configure_runtime, load_config, model_settings, project_root


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    doctor = sub.add_parser("doctor")
    plan = sub.add_parser("plan")
    audit = sub.add_parser("audit")
    audit.add_argument("--batch", required=True)
    run = sub.add_parser("run")
    run.add_argument("--batch", required=True)
    run.add_argument("--groups", nargs="+")
    run.add_argument("--tasks", nargs="+")
    run.add_argument("--resume", action="store_true")
    run.add_argument("--reuse-manifest", type=Path)
    run.add_argument("--network", choices=["public", "offline"])
    run.add_argument("--repeats", type=int)
    for command in (doctor, plan, run):
        command.add_argument("--config", type=Path, dest="experiment_config")
    child = sub.add_parser("child")
    child.add_argument("config", type=Path)
    args = parser.parse_args()
    root = project_root()
    configure_runtime(root)
    config = load_config(root, getattr(args, "experiment_config", None))
    if args.command == "child":
        import harbor.constants as constants
        from harbor.cli.main import app

        constants.CACHE_DIR = root / "artifacts/cache/harbor"
        constants.TASK_CACHE_DIR = constants.CACHE_DIR / "tasks"
        constants.PACKAGE_CACHE_DIR = constants.TASK_CACHE_DIR / "packages"
        constants.DATASET_CACHE_DIR = constants.CACHE_DIR / "datasets"
        constants.NOTIFICATIONS_PATH = constants.CACHE_DIR / "notifications.json"
        app(["run", "--config", str(args.config)])
        return
    from harnesslab.coding.runner import preflight_environment, run_batch, task_plan

    if args.command == "audit":
        from harnesslab.coding.audit import audit_batch

        report = audit_batch(root, args.batch)
        print(json.dumps({"batch": args.batch, "indexed_trials": len(report["trials"])}))
    elif args.command == "doctor":
        from sandbox_profile import load_profile

        settings = model_settings(root, require_key=False)
        rows = [task_plan(root, config, name) for name in config.tasks]
        for row in rows:
            preflight_environment(root, config, row)
        print(
            json.dumps(
                {
                    "model": settings["model"],
                    "key_configured": bool(settings["api_key"].strip()),
                    "sandbox": load_profile(root, ".env.sandbox").public_summary(),
                    "adapter_construction": "passed",
                    "tasks": rows,
                },
                indent=2,
            )
        )
    elif args.command == "plan":
        print(json.dumps([task_plan(root, config, name) for name in config.tasks], indent=2))
    else:
        updates = {}
        if args.network:
            updates["network_mode"] = args.network
        if args.repeats is not None:
            updates["repeats"] = args.repeats
        if args.groups:
            updates["groups"] = args.groups
        if args.tasks:
            if not set(args.tasks) <= set(config.tasks):
                parser.error("Task is outside the frozen six-task set")
            updates["tasks"] = args.tasks
        config = type(config).model_validate({**config.model_dump(), **updates})
        result = run_batch(root, config, args.batch, args.resume, args.reuse_manifest)
        print(json.dumps({k: v for k, v in result.items() if k != "outcomes"}, indent=2))
        sys.exit(0 if result["integration_passed"] else 1)


if __name__ == "__main__":
    main()
