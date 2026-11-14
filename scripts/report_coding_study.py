"""Summarize saved trials without rerunning models or changing source outcomes."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median

MEASURES = (
    "model_responses",
    "model_issued_tool_calls",
    "environment_commands",
    "environment_command_failures",
    "environment_command_seconds_sum",
    "agent_seconds",
    "trial_seconds",
    "submission_capture_seconds",
    "candidates",
    "evidence_checks",
    "input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "cached_input_tokens",
    "visible_text_chars",
    "reasoning_text_chars",
    "tool_argument_chars",
    "actor_model_calls",
    "grader_model_calls",
    "grader_input_tokens",
    "grader_output_tokens",
)


def read_json(path):
    return json.loads(path.read_text())


def distribution(values):
    values = sorted(value for value in values if value is not None)
    if not values:
        return {"observed_trials": 0, "sum": None, "mean": None, "median": None, "p90": None}
    position = (len(values) - 1) * 0.9
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return {
        "observed_trials": len(values),
        "sum": sum(values),
        "mean": mean(values),
        "median": median(values),
        "p90": values[lower] + (values[upper] - values[lower]) * (position - lower),
    }


def regrade_scores(paths):
    index = {}
    for path in paths:
        ledger = read_json(Path(path))
        if not ledger["ok"] or len(ledger["outcomes"]) != ledger["expected"]:
            raise ValueError("Regrade ledger is incomplete")
        for row in ledger["outcomes"]:
            source = row["source"]
            original = Path(source["outcome"]).resolve()
            if hashlib.sha256(original.read_bytes()).hexdigest() != source["outcome_sha256"]:
                raise ValueError("Regraded source outcome changed")
            if (
                hashlib.sha256(Path(source["manifest"]).read_bytes()).hexdigest()
                != source["manifest_sha256"]
            ):
                raise ValueError("Regraded submission manifest changed")
            result = row["regrade"]
            trial = Path(result["trial"])
            provenance = read_json(trial / "agent/regrade-provenance.json")
            official = read_json(trial / "result.json")
            tests = read_json(trial / "verifier/ctrf.json")["results"]["summary"]
            if (
                original in index
                or not row["accepted"]
                or row["model_calls"] != 0
                or not result["pipeline_ok"]
                or not result["cleanup_verified"]
                or not row["ctrf_summary"]["tests"]
                or tests != row["ctrf_summary"]
                or provenance["model_calls"] != 0
                or provenance["source_sha256"] != source["manifest_sha256"]
                or official["verifier_result"]["rewards"]["reward"] != row["reward"]
                or row["reward"] is None
            ):
                raise ValueError("Regrade lacks unique official score and provenance")
            index[original] = row
    return index


def make_report(root, config, batches, regrades=()):
    recovered = regrade_scores(regrades)
    used_regrades = set()
    records = []
    for batch in batches:
        for path in sorted((root / "artifacts/coding" / batch).glob("*.outcome.json")):
            row = read_json(path)
            if row.get("group") not in config["groups"]:
                continue
            metrics = row.get("metrics") or {}
            regrade = recovered.get(path.resolve())
            if regrade is not None:
                if row["reward"] is not None or regrade["cell"] != [
                    row["network_mode"],
                    row["task"],
                    row["group"],
                    row["repeat"],
                ]:
                    raise ValueError("Regrades cannot replace an existing score or another cell")
                used_regrades.add(path.resolve())
            trial = Path(row["trial"]) if row.get("trial") else None
            saved_metrics = trial / "agent/metrics.json" if trial else None
            if not metrics and saved_metrics and saved_metrics.exists():
                metrics = read_json(saved_metrics)
            trace = row.get("langsmith") or {}
            monitoring_path = trial / "agent/langsmith-metrics.json" if trial else None
            monitoring = (
                read_json(monitoring_path) if monitoring_path and monitoring_path.exists() else {}
            )
            lengths = metrics.get("tokens_and_lengths") or {}
            metadata = (row.get("agent_result") or {}).get("metadata") or {}
            started = metadata.get("started_model_calls")
            received = metrics.get("model_responses")
            record = {
                "task": row["task"],
                "group": row["group"],
                "network": row.get("network_mode", config.get("network_mode", "public")),
                "repeat": row["repeat"],
                "batch": batch,
                "job_name": row["job_name"],
                "pipeline_ok": row["pipeline_ok"],
                "reward": regrade["reward"] if regrade else row["reward"],
                "original_reward": row["reward"],
                "score_source": "saved_submission_regrade" if regrade else "original_verifier",
                "regrade_trial": regrade["regrade"]["trial"] if regrade else None,
                "response_transport": (metadata.get("configuration") or {}).get(
                    "response_transport", "non_streaming"
                ),
                "started_model_calls": started,
                "usage_completeness": ("partial" if started > received else "complete")
                if started is not None and received is not None
                else "not_reported",
                "deadline_stop": (row.get("exception") or {}).get("exception_type")
                == "AgentTimeoutError",
                "error_type": (row.get("exception") or {}).get("exception_type"),
                "cleanup_verified": row["cleanup_verified"],
                "metrics_present": bool(metrics),
                "submission_record_present": bool(metrics.get("submission")),
                "submission_artifact_present": bool(
                    (metrics.get("submission") or {}).get("sha256")
                ),
                "langsmith_status": trace.get("status"),
                "langsmith_feedback": "verified"
                if monitoring.get("verified")
                else trace.get("feedback_status"),
                "langsmith_url": trace.get("url"),
                "trial": row.get("trial"),
                "outcome_path": str(path),
                "reuse": row.get("reuse"),
            }
            record.update({key: lengths.get(key, metrics.get(key)) for key in MEASURES})
            roles = metrics.get("role_usage") or {}
            record.update(
                actor_model_calls=(roles.get("actor") or {}).get(
                    "model_calls",
                    metrics.get("model_responses") if row["group"] == "mini" else None,
                ),
                grader_model_calls=(roles.get("grader") or {}).get("model_calls"),
                grader_input_tokens=(roles.get("grader") or {}).get("input_tokens"),
                grader_output_tokens=(roles.get("grader") or {}).get("output_tokens"),
            )
            records.append(record)
    if used_regrades != set(recovered):
        raise ValueError("A regraded cell is outside the selected report batches")
    cells = defaultdict(list)
    for row in records:
        cells[(row["network"], row["task"], row["group"], row["repeat"])].append(row)
    duplicate_valid = [
        key for key, rows in cells.items() if sum(r["reward"] is not None for r in rows) > 1
    ]
    if duplicate_valid:
        raise ValueError(
            f"Multiple official scores for a cell; select batches explicitly: {duplicate_valid}"
        )
    selected = {
        key: next((r for r in rows if r["reward"] is not None), rows[-1])
        for key, rows in cells.items()
    }
    groups = []
    for network in ("offline", "public"):
        for group in config["groups"]:
            rows = [r for r in selected.values() if r["network"] == network and r["group"] == group]
            valid = [r for r in rows if r["reward"] is not None]
            successes = sum(r["reward"] == 1 for r in valid)
            all_rows = [r for r in records if r["network"] == network and r["group"] == group]
            usage = {key: distribution([r[key] for r in all_rows]) for key in MEASURES}
            groups.append(
                {
                    "network": network,
                    "group": group,
                    "planned_cells": len(config["tasks"]) * config["repeats"],
                    "finished_cells": len(rows),
                    "valid_scored_cells": len(valid),
                    "infrastructure_error_cells": len(rows) - len(valid),
                    "scored_pipeline_error_cells": sum(not r["pipeline_ok"] for r in valid),
                    "pipeline_error_cells": sum(not r["pipeline_ok"] for r in rows),
                    "successes": successes,
                    "success_rate": successes / len(valid) if valid else None,
                    "deadline_stops": sum(r["deadline_stop"] for r in rows),
                    "regraded_cells": sum(
                        r["score_source"] == "saved_submission_regrade" for r in rows
                    ),
                    "partial_usage_trials": sum(
                        r["usage_completeness"] == "partial" for r in all_rows
                    ),
                    "transport_counts": dict(Counter(r["response_transport"] for r in rows)),
                    "ended_attempts_including_replacements": len(all_rows),
                    "all_ended_attempt_usage": usage,
                    "output_tokens_per_success": usage["output_tokens"]["sum"] / successes
                    if successes and usage["output_tokens"]["sum"] is not None
                    else None,
                }
            )
    cases = []
    for key, treatment in selected.items():
        network, task, group, repeat = key
        if group == "mini":
            continue
        baseline_group = "mini" if group == "deepagents_default" else "deepagents_default"
        base = selected.get((network, task, baseline_group, repeat))
        if not base or base["reward"] is None or treatment["reward"] is None:
            continue
        label = "same_result"
        if treatment["reward"] > base["reward"]:
            label = "improvement_to_inspect"
        elif treatment["reward"] < base["reward"]:
            label = "regression_to_inspect"
        elif treatment["reward"] == 1:
            label = "successful_cost_comparison"
        cases.append(
            {
                "task": task,
                "network": network,
                "group": group,
                "baseline_group": baseline_group,
                "label": label,
                "base_trial": base["trial"],
                "treatment_trial": treatment["trial"],
                "base_reward": base["reward"],
                "treatment_reward": treatment["reward"],
                "base_pipeline_ok": base["pipeline_ok"],
                "treatment_pipeline_ok": treatment["pipeline_ok"],
                "review_candidates": treatment["candidates"],
                "evidence_checks": treatment["evidence_checks"],
                "output_token_delta": treatment["output_tokens"] - base["output_tokens"]
                if treatment["output_tokens"] is not None and base["output_tokens"] is not None
                else None,
                "tool_call_delta": treatment["model_issued_tool_calls"]
                - base["model_issued_tool_calls"]
                if treatment["model_issued_tool_calls"] is not None
                and base["model_issued_tool_calls"] is not None
                else None,
            }
        )
    network_pairs = []
    for key, offline in selected.items():
        network, task, group, repeat = key
        public = selected.get(("public", task, group, repeat))
        if (
            network != "offline"
            or not public
            or offline["reward"] is None
            or public["reward"] is None
        ):
            continue
        network_pairs.append(
            {
                "task": task,
                "group": group,
                "offline_reward": offline["reward"],
                "public_reward": public["reward"],
                "offline_trial": offline["trial"],
                "public_trial": public["trial"],
                "offline_pipeline_ok": offline["pipeline_ok"],
                "public_pipeline_ok": public["pipeline_ok"],
            }
        )
    return {
        "configuration": config,
        "batches": batches,
        "groups": groups,
        "trials": records,
        "case_candidates": cases,
        "network_pairs": network_pairs,
        "definitions": {
            "success_rate": (
                "Official successes / all official scores, including scored harness/review errors."
            ),
            "infrastructure_error_cells": (
                "Ended cells without an official score; excluded from the score denominator "
                "and retained in usage."
            ),
            "scored_pipeline_error_cells": (
                "Scored cells with a separate integration error; retained in the score denominator."
            ),
            "usage": "All ended attempts, including infrastructure failures.",
            "partial_usage": (
                "Started requests without a complete response may have unreported billable usage; "
                "recorded totals are observed usage only."
            ),
            "regrades": (
                "Saved-submission scores retain the original pipeline error and original actor "
                "usage; no second actor attempt is added."
            ),
            "missing": "Missing measurements stay null; observed_trials is the metric denominator.",
            "cases": "Inspection candidates, not causal explanations or hacking verdicts.",
            "repetitions": "One independent attempt per cell; no best-of-N selection.",
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--config", default="configs/coding-tb21-study.json")
    parser.add_argument("--batches", nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--regrades", type=Path, nargs="*", default=[])
    args = parser.parse_args()
    report = make_report(args.root, read_json(args.root / args.config), args.batches, args.regrades)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    if report["trials"]:
        with (args.output / "trials.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(report["trials"][0]))
            writer.writeheader()
            writer.writerows(report["trials"])
    columns = [
        "network",
        "group",
        "planned_cells",
        "finished_cells",
        "valid_scored_cells",
        "successes",
        "success_rate",
        "infrastructure_error_cells",
        "scored_pipeline_error_cells",
        "pipeline_error_cells",
        "deadline_stops",
    ]
    with (args.output / "groups.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(report["groups"])
    print(
        json.dumps(
            {
                "ended_trials": len(report["trials"]),
                "case_candidates": len(report["case_candidates"]),
                "output": str(args.output),
            }
        )
    )


if __name__ == "__main__":
    main()
