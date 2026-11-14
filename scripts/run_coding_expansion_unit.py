"""Run one frozen full-study unit after the complete six-task pilot passes its evidence gate."""

from __future__ import annotations

import argparse
import itertools
import json
import os
import subprocess
from pathlib import Path

from harnesslab.coding.config import CodingConfig, configure_runtime, project_root, save_json
from harnesslab.coding.observability import measurements
from harnesslab.coding.reuse import checked_json, digest
from harnesslab.coding.runner import build_plan, run_batch

PROTOCOL_FIELDS = (
    "thinking",
    "reasoning_effort",
    "temperature",
    "top_p",
    "context_window_tokens",
    "max_model_calls",
    "max_output_tokens",
    "request_timeout",
    "command_timeout",
    "repeats",
    "max_review_iterations",
    "langsmith_tracing",
)


def pilot_gate(study: dict) -> dict:
    target = study["configuration"]
    if study.get("image_amendment"):
        for name in ("canary", "retirement"):
            reference = study["image_amendment"][name]
            checked_json(Path(reference["path"]), reference["sha256"])
    expected = set(
        itertools.product(("offline", "public"), study["pilot_tasks"], target["groups"], [0])
    )
    found, discarded = {}, []
    for batch in map(Path, study["pilot_batches"]):
        source = json.loads((batch / "plan.json").read_text())
        before = source["configuration"].get("response_transport", "non_streaming")
        after = target.get("response_transport", "non_streaming")
        if before != after:
            amendment = study.get("transport_amendment") or {}
            if amendment.get("from") != before or amendment.get("to") != after:
                raise ValueError("Pilot transport difference lacks an explicit amendment")
            for reference in (amendment["canary"], amendment["retirement"]):
                checked_json(Path(reference["path"]), reference["sha256"])
        if any(source["configuration"][key] != target[key] for key in PROTOCOL_FIELDS):
            raise ValueError("Pilot model protocol differs from the full study")
        if any(source[key] != value for key, value in study["model_profile"].items()):
            raise ValueError("Pilot model profile differs from the full study")
        for path in batch.glob("*.outcome.json"):
            row = json.loads(path.read_text())
            key = (row["network_mode"], row["task"], row["group"], row["repeat"])
            if key not in expected:
                continue
            if row["reward"] is None:
                discarded.append({"path": str(path), "sha256": digest(path)})
                continue
            metrics = row.get("metrics") or {}
            lengths = metrics.get("tokens_and_lengths") or {}
            if (
                not row["cleanup_verified"]
                or any(
                    metrics.get(name) is None
                    for name in (
                        "model_responses",
                        "model_issued_tool_calls",
                        "agent_seconds",
                        "trial_seconds",
                    )
                )
                or any(
                    lengths.get(name) is None
                    for name in (
                        "input_tokens",
                        "output_tokens",
                        "visible_text_chars",
                        "reasoning_text_chars",
                        "tool_argument_chars",
                    )
                )
            ):
                raise ValueError("Pilot score lacks complete usage, timing or cleanup evidence")
            feedback = None
            if row["group"] != "mini":
                receipt_path = Path(row["trial"]) / "agent/langsmith-metrics.json"
                receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
                if not receipt.get("verified") or receipt.get("measurements") != measurements(row):
                    raise ValueError(
                        "Pilot Deep Agents metrics lack a matching verified LangSmith receipt"
                    )
                feedback = {"path": str(receipt_path), "sha256": digest(receipt_path)}
            if key in found:
                raise ValueError("Pilot has more than one scored attempt for a cell")
            found[key] = {
                "cell": list(key),
                "path": str(path),
                "sha256": digest(path),
                "reward": row["reward"],
                "langsmith_receipt": feedback,
            }
    if set(found) != expected:
        raise ValueError(f"Pilot gate incomplete: {len(found)}/{len(expected)} scored cells")
    return {
        "ok": True,
        "preserved_cells": list(found.values()),
        "unscored_attempts_retained": discarded,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--study-sha256", required=True)
    parser.add_argument("--unit", type=int, default=None)
    args = parser.parse_args()
    root = project_root()
    configure_runtime(root)
    study = checked_json(args.study, args.study_sha256)
    if amendment := study.get("python_amendment"):
        for name in ("acceptance", "retirement"):
            reference = amendment[name]
            checked_json(reference["path"], reference["sha256"])
    unit_index = args.unit if args.unit is not None else int(os.environ["SLURM_ARRAY_TASK_ID"])
    if not 0 <= unit_index < len(study["units"]):
        raise ValueError("Execution unit is outside the frozen expansion plan")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    if head != study["git_commit"] or any(
        digest(root / name) != sha for name, sha in study["script_hashes"].items()
    ):
        raise ValueError("Expansion checkout changed after preparation")
    unit = study["units"][unit_index]
    config = CodingConfig.model_validate(checked_json(root / unit["config"], unit["config_sha256"]))
    plan = build_plan(root, config)
    if plan["source_hashes"] != study["source_hashes"] or any(
        plan[key] != value for key, value in study["model_profile"].items()
    ):
        raise ValueError("Expansion runtime or model profile changed")
    controls = root / study["controls_manifest"]
    checked_json(controls, study["controls_sha256"])
    gate = pilot_gate(study)
    gate_path = args.study.parent / "pilot-gates" / f"{unit_index:03}.json"
    save_json(gate_path, gate)
    result = run_batch(root, config, unit["batch"], controls_manifest=controls)
    print(
        json.dumps(
            {
                "unit": unit_index,
                "task": unit["task"],
                "network": unit["network"],
                "expected": result["expected_model_runs"],
                "ended": result["completed_model_runs"],
                "integration_passed": result["integration_passed"],
            }
        )
    )
    raise SystemExit(0 if result["integration_passed"] else 1)


if __name__ == "__main__":
    main()
