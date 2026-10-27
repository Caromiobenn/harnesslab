"""Recompute quality, grader disagreement, costs, and paired instance bootstrap intervals."""

# ruff: noqa: RUF001 -- Chinese report prose uses Chinese punctuation.

from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median

from harnesslab.study import validate_run_fingerprint, validate_study_progress


def paired_interval(rows: dict, arm: str, baseline: str) -> dict:
    left = rows[arm]
    right = rows[baseline]
    common = sorted(set(left) & set(right))
    clusters = defaultdict(list)
    for task_ref, seed in common:
        clusters[task_ref].append(
            int(left[(task_ref, seed)]["success"]) - int(right[(task_ref, seed)]["success"])
        )
    if not clusters:
        return {"paired_runs": 0, "delta": None, "ci95": None}
    families = defaultdict(list)
    for task_ref, values in clusters.items():
        families[task_ref.split(".")[1]].append(mean(values))
    rng = random.Random(20261025)
    draws = []
    for _ in range(5000):
        sample = []
        for values in families.values():
            sample.extend(rng.choices(values, k=len(values)))
        draws.append(mean(sample))
    draws.sort()
    return {
        "paired_runs": len(common),
        "instance_clusters": len(clusters),
        "delta": mean([mean(values) for values in clusters.values()]),
        "ci95": [draws[125], draws[4874]],
        "interval_scope": "stratified instance bootstrap conditional on these 3 families",
    }


def analyze(root: Path) -> dict:
    manifest = json.loads((root / "study-manifest.json").read_text())
    progress = [
        json.loads(line) for line in (root / "progress.jsonl").read_text().splitlines() if line
    ]
    missing = validate_study_progress(manifest, progress)
    arms = defaultdict(list)
    paired = defaultdict(dict)
    for job in progress:
        directory = Path(job["artifact_directory"])
        if not directory.exists():
            directory = root / "runs" / directory.name
        records = [
            json.loads(line) for line in (directory / "runs.jsonl").read_text().splitlines() if line
        ]
        if len(records) != 1:
            raise ValueError("each scheduled job must have exactly one run record")
        record = records[0]
        validate_run_fingerprint(
            manifest,
            job["arm"],
            json.loads((directory / "manifest.json").read_text()),
            job["task_ref"],
        )
        if record["task_id"] != job["task_ref"] or record["seed"] != job["seed"]:
            raise ValueError("progress and raw records disagree")
        arms[job["arm"]].append(record)
        key = (record["task_id"], record["seed"])
        if key in paired[job["arm"]]:
            raise ValueError("duplicate task/seed within treatment")
        paired[job["arm"]][key] = record
    summary = {}
    for arm, records in arms.items():
        successes = sum(record["success"] for record in records)
        accepted = [record for record in records if record["diagnostics"].get("runtime_accepted")]
        total_tokens = [
            record["metrics"]["input_tokens"] + record["metrics"]["output_tokens"]
            for record in records
        ]
        raw_satisfied = false_satisfied = recovered = regressed = initial_failures = 0
        verdicts = Counter()
        families = defaultdict(lambda: [0, 0])
        for record in records:
            family = record["task_id"].split(".")[1]
            families[family][0] += int(record["success"])
            families[family][1] += 1
            diagnostics = record["diagnostics"]
            candidates = diagnostics.get("candidate_evaluations", [])
            evaluations = diagnostics.get("rubric_evaluations", [])
            if evaluations:
                verdicts[evaluations[-1]["result"]] += 1
            for candidate, evaluation in zip(candidates, evaluations, strict=False):
                if evaluation["result"] == "satisfied":
                    raw_satisfied += 1
                    false_satisfied += int(not candidate["passed"])
            if candidates:
                first = candidates[0]["passed"]
                initial_failures += int(not first)
                recovered += int(not first and record["success"])
                regressed += int(first and not record["success"])
        role_totals = {}
        for role in ["actor", "grader"]:
            role_totals[role] = {
                key: sum(
                    record["diagnostics"].get("role_usage", {}).get(role, {}).get(key, 0)
                    for record in records
                )
                for key in ["model_calls", "input_tokens", "output_tokens"]
            }
        summary[arm] = {
            "runs": len(records),
            "successes": successes,
            "success_rate": successes / len(records),
            "execution_errors": sum(record["status"] == "error" for record in records),
            "runtime_accepted": len(accepted),
            "false_accepts": sum(not record["success"] for record in accepted),
            "raw_satisfied": raw_satisfied,
            "false_satisfied": false_satisfied,
            "initial_failures": initial_failures,
            "recovered": recovered,
            "regressed": regressed,
            "mean_tokens": mean(total_tokens),
            "tokens_per_success": sum(total_tokens) / successes if successes else None,
            "mean_seconds": mean(record["metrics"]["duration_ms"] / 1000 for record in records),
            "median_seconds": median(record["metrics"]["duration_ms"] / 1000 for record in records),
            "final_grader_verdicts": dict(verdicts),
            "role_totals": role_totals,
            "by_family": {
                key: {"successes": values[0], "runs": values[1]}
                for key, values in sorted(families.items())
            },
        }
    comparisons = {}
    for arm, baseline in [
        ("generic_retry", "default"),
        ("rubric_transcript", "generic_retry"),
        ("rubric_evidence", "generic_retry"),
        ("rubric_evidence", "rubric_transcript"),
    ]:
        comparisons[f"{arm}_vs_{baseline}"] = paired_interval(paired, arm, baseline)
    return {
        "protocol": manifest["protocol"],
        "split": manifest["split"],
        "completed": len(progress),
        "scheduled": len(manifest["schedule"]),
        "complete": not missing,
        "missing_job_keys": missing,
        "arms": summary,
        "paired_comparisons": comparisons,
        "limits": [
            "same-model grader may share actor blind spots",
            "equal budget ceilings are not equal realized compute",
            "synthetic instances from only 3 task families",
            "holdout separates instances, not unseen task families",
            "self-hosted token counts are not billed USD",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    report = analyze(args.root)
    (args.root / "analysis.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    lines = [
        "# Qwen3.5-9B Rubric 实验",
        "",
        f"状态：{'已完成' if report['complete'] else '进行中'}；"
        f"{report['completed']}/{report['scheduled']} 次运行，数据划分：{report['split']}。",
        "",
        "| 组别 | 外部验收通过 | 执行错误 | 平均 token | 平均秒数 | 失败修复/初始失败 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for arm, values in report["arms"].items():
        lines.append(
            f"| {arm} | {values['successes']}/{values['runs']} | "
            f"{values['execution_errors']} | {values['mean_tokens']:.0f} | "
            f"{values['mean_seconds']:.1f} | {values['recovered']}/{values['initial_failures']} |"
        )
    lines.extend(["", "配对成功率差及按实例分层 bootstrap 的 95% 区间：", ""])
    for key, value in report["paired_comparisons"].items():
        if value["delta"] is not None:
            low, high = value["ci95"]
            lines.append(
                f"- {key}：{value['delta']:+.1%}，[{low:+.1%}, {high:+.1%}]；"
                f"{value['paired_runs']} 对运行、{value['instance_clusters']} 个实例。"
            )
    lines.extend(
        [
            "",
            "区间只描述当前三个任务族中的实例变化。重复采样不作为独立任务；"
            "数据来自合成任务，留出的是输入实例，不是未见过的任务类型。",
            "",
            "预算上限相同，实际算力消耗不同，须结合 token 和延迟判断。"
            "评分模型与执行模型相同，可能共享盲点。任务成功由隐藏确定性验收决定。",
            "",
            "逐组误放行、评分状态、修复与退化、模型角色用量见 analysis.json；"
            "原始结果位于 runs/，执行顺序和代码哈希见 study-manifest.json。",
        ]
    )
    (args.root / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "complete": report["complete"],
                "completed": report["completed"],
                "scheduled": report["scheduled"],
                "arms": report["arms"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
