"""Compare matched tasks using frozen scores and all observed attempt costs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from report_coding_study import MEASURES, distribution


def cell_key(row):
    return row["network"], row["task"], row["group"], row["repeat"]


def runtime(row):
    return {
        key: row.get(key)
        for key in ("response_transport", "request_adapter", "effective_model_profile")
    }


def observed_metric(rows, metric):
    values = [row.get(metric) for row in rows if row.get(metric) is not None]
    return {
        "observed_sum": sum(values) if values else None,
        "missing_attempts": len(rows) - len(values),
    }


def comparisons(groups):
    for network in ("offline", "public"):
        for group in groups:
            baseline = "mini" if group == "deepagents_default" else "deepagents_default"
            if group != "mini" and baseline in groups:
                yield {
                    "kind": "harness",
                    "baseline_group": baseline,
                    "treatment_group": group,
                    "baseline_network": network,
                    "treatment_network": network,
                }
    for group in groups:
        yield {
            "kind": "network",
            "baseline_group": group,
            "treatment_group": group,
            "baseline_network": "offline",
            "treatment_network": "public",
        }


def paired_report(report):
    config = report["configuration"]
    attempts, scored, sources = defaultdict(list), {}, set()
    for row in report["trials"]:
        source = row["outcome_path"]
        if source in sources:
            raise ValueError("Duplicate outcome would count costs twice")
        sources.add(source)
        key = cell_key(row)
        attempts[key].append(row)
        if row["reward"] is not None:
            if key in scored:
                raise ValueError("Multiple official scores for one cell")
            scored[key] = row
    pairs, coverage, buckets = [], [], defaultdict(list)
    for comparison in comparisons(config["groups"]):
        count = 0
        for task in config["tasks"]:
            for repeat in range(config["repeats"]):
                keys = [
                    (comparison[side + "_network"], task, comparison[side + "_group"], repeat)
                    for side in ("baseline", "treatment")
                ]
                if any(key not in scored for key in keys):
                    continue
                count += 1
                base, treatment = (scored[key] for key in keys)
                pair = {
                    **comparison,
                    "task": task,
                    "repeat": repeat,
                    "baseline_reward": base["reward"],
                    "treatment_reward": treatment["reward"],
                    "reward_delta": treatment["reward"] - base["reward"],
                    "metrics": {},
                }
                for side, key, row in zip(
                    ("baseline", "treatment"), keys, (base, treatment), strict=True
                ):
                    pair.update(
                        {
                            side + "_trial": row["trial"],
                            side + "_outcome_path": row["outcome_path"],
                            side + "_score_source": row["score_source"],
                            side + "_pipeline_ok": row["pipeline_ok"],
                            side + "_error_type": row.get("error_type"),
                            side + "_runtime": runtime(row),
                            side + "_attempts": len(attempts[key]),
                            side + "_partial_usage_attempts": sum(
                                r["usage_completeness"] == "partial" for r in attempts[key]
                            ),
                            side + "_unknown_usage_attempts": sum(
                                r["usage_completeness"] == "not_reported" for r in attempts[key]
                            ),
                        }
                    )
                for metric in MEASURES:
                    left, right = (observed_metric(attempts[key], metric) for key in keys)
                    a, b = left["observed_sum"], right["observed_sum"]
                    pair["metrics"][metric] = {
                        "baseline": left,
                        "treatment": right,
                        "observed_delta": b - a if a is not None and b is not None else None,
                    }
                pairs.append(pair)
                cohort = {
                    **comparison,
                    "baseline_runtime": runtime(base),
                    "treatment_runtime": runtime(treatment),
                }
                buckets[json.dumps(cohort, sort_keys=True)].append(pair)
        expected = len(config["tasks"]) * config["repeats"]
        coverage.append({**comparison, "expected_pairs": expected, "scored_pairs": count})
    summaries = []
    for key, rows in sorted(buckets.items()):
        summary = {
            **json.loads(key),
            "paired_cells": len(rows),
            "tasks": sorted({row["task"] for row in rows}),
            "baseline_successes": sum(row["baseline_reward"] == 1 for row in rows),
            "treatment_successes": sum(row["treatment_reward"] == 1 for row in rows),
            "improvements": sum(row["reward_delta"] > 0 for row in rows),
            "regressions": sum(row["reward_delta"] < 0 for row in rows),
            "both_pass": sum(
                row["baseline_reward"] == row["treatment_reward"] == 1 for row in rows
            ),
            "both_fail": sum(
                row["baseline_reward"] == row["treatment_reward"] == 0 for row in rows
            ),
            "metrics": {},
        }
        for metric in MEASURES:
            values = [row["metrics"][metric] for row in rows]
            matched = [value for value in values if value["observed_delta"] is not None]
            summary["metrics"][metric] = {
                "paired_cells_with_values": len(matched),
                "baseline": distribution([v["baseline"]["observed_sum"] for v in matched]),
                "treatment": distribution([v["treatment"]["observed_sum"] for v in matched]),
                "delta": distribution([v["observed_delta"] for v in matched]),
                "baseline_missing_attempts": sum(v["baseline"]["missing_attempts"] for v in values),
                "treatment_missing_attempts": sum(
                    v["treatment"]["missing_attempts"] for v in values
                ),
            }
        for side in ("baseline", "treatment"):
            for field in ("attempts", "partial_usage_attempts", "unknown_usage_attempts"):
                summary[side + "_" + field] = sum(row[side + "_" + field] for row in rows)
        summaries.append(summary)
    return {
        "coverage": coverage,
        "comparisons": summaries,
        "pairs": pairs,
        "definitions": {
            "matching": "Same task and repeat, with official scores on both sides.",
            "delta": "Treatment minus baseline; network comparisons use public minus offline.",
            "costs": "Observed costs of all ended attempts in matched cells, including failures.",
            "metric_denominator": "Each metric compares only pairs with a value on both sides.",
            "missing": "Nulls remain null; missing attempt counts and partial usage are separate.",
            "cohorts": "Summaries split by the runtime configuration on both sides of each pair.",
            "scope": "Paired differences describe incomplete coverage, not causal effects.",
        },
    }


def write_pairs(report, output):
    output.mkdir(parents=True, exist_ok=True)
    (output / "pairs.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    tables = {"coverage": report["coverage"], "comparisons": [], "costs": [], "pairs": []}
    for index, row in enumerate(report["comparisons"]):
        flat = {key: value for key, value in row.items() if key != "metrics"}
        tables["comparisons"].append({"comparison_id": index, **flat})
        for metric, value in row["metrics"].items():
            cost = {
                "comparison_id": index,
                "metric": metric,
                **{key: item for key, item in value.items() if not isinstance(item, dict)},
            }
            for side in ("baseline", "treatment", "delta"):
                cost.update({side + "_" + key: item for key, item in value[side].items()})
            tables["costs"].append(cost)
    for row in report["pairs"]:
        flat = {key: value for key, value in row.items() if key != "metrics"}
        for metric, value in row["metrics"].items():
            flat[metric + "_observed_delta"] = value["observed_delta"]
        tables["pairs"].append(flat)
    for name, rows in tables.items():
        if not rows:
            continue
        with (output / (name + ".csv")).open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {
                        k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
                        for k, v in row.items()
                    }
                )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--report-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = args.report.read_bytes()
    if hashlib.sha256(raw).hexdigest() != args.report_sha256:
        raise ValueError("Source report hash changed")
    report = paired_report(json.loads(raw))
    report["source"] = {"path": str(args.report.resolve()), "sha256": args.report_sha256}
    write_pairs(report, args.output)
    print(
        json.dumps(
            {
                "pairs": len(report["pairs"]),
                "cohorts": len(report["comparisons"]),
                "output": str(args.output),
            }
        )
    )


if __name__ == "__main__":
    main()
