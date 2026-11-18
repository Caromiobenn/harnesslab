"""Summarize an isolated CLI study batch and check the saved regex case evidence."""

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from statistics import median

HERE = Path(__file__).resolve().parent
HISTORY = (
    HERE.parent
    / "deliverables"
    / "2026-11-13-harnesslab-coding"
    / "verified-publication"
    / "artifacts"
    / "coding-cases"
)
CELL_KEYS = ("task", "requirement", "toolchain", "repeat")
OUTCOMES = (
    "qualified",
    "definite_requirement_miss",
    "requirement_unresolved",
    "function_failed",
    "unscorable",
    "pipeline_error",
    "pending",
)
DEFINITE_MISSES = {
    "missing_executable",
    "non_native_executable",
    "missing_c_source",
    "source_did_not_build",
}
LABELS = {
    "qualified": "两项都达标",
    "definite_requirement_miss": "功能通过，明确缺交付要求",
    "requirement_unresolved": "功能通过，交付要求无法确认",
    "function_failed": "功能未通过",
    "unscorable": "最终评分不可用",
    "pipeline_error": "运行链路出错",
    "pending": "未生成结果",
}


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def witness(path):
    return {"file": path.as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def historical_cases(directory):
    if not directory.is_dir():
        return None
    repair_dir = directory / "regex-evidence-repair"
    self_dir = directory / "regex-self-review"
    repair = load(repair_dir / "verified.json")
    repair_evidence = load(repair_dir / "evidence.json")
    review = load(self_dir / "verified.json")
    versions = [repair_dir / name for name in ("initial-regex.txt", "final-regex.txt")]
    hashes = [witness(path) for path in versions]
    verified = all(
        hashes[index]["sha256"] == repair[f"{phase}_sha256"]
        for index, phase in enumerate(("initial", "final"))
    )
    actual = [
        re.findall(
            path.read_text(encoding="utf-8").strip(),
            repair_evidence["counterexample"],
            re.MULTILINE,
        )
        for path in versions
    ]
    checks = actual == [repair["initial_matches"], repair["final_matches"]]
    if not verified or not checks:
        raise ValueError("Historical regex artifact or counterexample differs from saved receipt")
    return {
        "repair": {
            "artifact_hashes_checked": verified,
            "counterexample_reproduced": checks,
            "initial_counterexample_matches": actual[0],
            "final_counterexample_matches": actual[1],
            "official_initial_reward": repair_evidence["official_initial_reward"],
            "official_final_reward": repair["official_final_reward"],
            "evidence": [witness(repair_dir / name) for name in ("verified.json", "evidence.json")]
            + hashes,
        },
        "unmodified_review": {
            "byte_identical_as_recorded": review["initial_equals_final_bytes"],
            "artifact_sha256_as_recorded": review["artifact_sha256"],
            "official_final_reward": review["official_reward"],
            "additional_review": review["additional_self_review"],
            "additional_seconds": review["additional_seconds"],
            "evidence": [witness(self_dir / name) for name in ("verified.json", "evidence.json")],
        },
    }


def outcome(score):
    if score.get("function_pass") is False:
        return "function_failed"
    if score.get("function_pass") is not True:
        return "unscorable"
    if score.get("qualified") is True:
        return "qualified"
    if score.get("requirements_status") in DEFINITE_MISSES:
        return "definite_requirement_miss"
    return "requirement_unresolved"


def first_pass(events, field):
    event = next((e for e in events if e.get("score", {}).get(field) is True), None)
    if event is not None:
        return {key: event.get(key) for key in ("seconds", "responses", "tool_calls", "digest")}
    return None


def transition(before, after):
    left, right = [outcome(e.get("score", {})) for e in (before, after)]
    if left in {"unscorable", "requirement_unresolved"} or right in {
        "unscorable",
        "requirement_unresolved",
    }:
        return "unresolved"
    if (left == "qualified") == (right == "qualified"):
        if before.get("digest") == after.get("digest"):
            return "same_submission"
        return "changed_same_outcome"
    return "improved" if right == "qualified" else "regressed"


def run_cell(directory, key, review_enabled):
    meta = dict(zip(CELL_KEYS, key, strict=True))
    result_path = directory / "result.json"
    if not result_path.is_file():
        return dict(meta, outcome="pending")
    trial = load(result_path)
    if any(trial.get(name) != expected for name, expected in meta.items()):
        raise ValueError(f"Cell identity mismatch in {result_path}")
    score = trial.get("score", {})
    label = "pipeline_error" if trial.get("status") == "pipeline_error" else outcome(score)
    row = dict(
        meta,
        outcome=label,
        status=trial.get("status"),
        score=score,
        metrics=trial.get("metrics", {}),
        score_status=trial.get("score_status"),
        served_model=trial.get("served_model"),
        result=witness(result_path),
    )
    if "langsmith" in trial:
        row["langsmith"] = trial["langsmith"]
    timeline_path = directory / "timeline.json"
    if not timeline_path.is_file() or label in {"unscorable", "pipeline_error"}:
        return row
    events = load(timeline_path)
    if not events or events[-1].get("label") != "final":
        return row
    first_candidate = next((e for e in events if e.get("label") == "first_candidate"), None)
    function = first_pass(events, "function_pass")
    qualified = first_pass(events, "qualified")
    timeline_has_scoring_gap = any(outcome(e.get("score", {})) == "unscorable" for e in events)
    row["timeline"] = {
        "file": witness(timeline_path),
        "complete_scores": not timeline_has_scoring_gap,
        "first_function_pass": function,
        "first_qualified": qualified,
        "seconds_function_to_qualified": (
            round(qualified["seconds"] - function["seconds"], 3) if function and qualified else None
        ),
        "first_candidate_present": first_candidate is not None,
    }
    if first_candidate is not None and review_enabled:
        final = events[-1]
        review = {
            "transition": transition(first_candidate, final),
            "first_candidate_outcome": outcome(first_candidate.get("score", {})),
            "first_candidate_sha256": first_candidate.get("digest"),
            "final_sha256": final.get("digest"),
        }
        for measure in ("responses", "tool_calls", "seconds", "tokens"):
            if isinstance(final.get(measure), (int, float)) and isinstance(
                first_candidate.get(measure), (int, float)
            ):
                review[measure] = round(final[measure] - first_candidate[measure], 3)
        review["token_reporting_complete"] = (
            row["metrics"].get("model_responses") == row["metrics"].get("usage_reported")
            and "usage_reported" in row["metrics"]
        )
        row["review"] = review
    return row


def tally(rows):
    counts = Counter(row["outcome"] for row in rows)
    valid = sum(counts[key] for key in OUTCOMES[:4])
    scored_rows = [row for row in rows if row["outcome"] in OUTCOMES[:4]]
    return {
        **{key: counts[key] for key in OUTCOMES},
        "planned": len(rows),
        "received": len(rows) - counts["pending"],
        "valid_final": valid,
        "function_pass": sum(counts[key] for key in OUTCOMES[:3]),
        "definite_miss_fraction": counts["definite_requirement_miss"] / valid if valid else None,
        "miss_fraction_if_all_unresolved_miss": (
            (counts["definite_requirement_miss"] + counts["requirement_unresolved"]) / valid
            if valid
            else None
        ),
        "artifact_kinds": dict(
            Counter(row["score"].get("artifact_kind") or "unrecorded" for row in scored_rows)
        ),
    }


def grouped(rows, names):
    groups = {}
    for row in rows:
        key = tuple(row[name] for name in names)
        groups.setdefault(key, []).append(row)
    return [dict(zip(names, key, strict=True), **tally(groups[key])) for key in sorted(groups)]


def cost_metrics(events):
    metrics = {}
    for measure in ("responses", "tool_calls", "seconds", "tokens"):
        values = [entry[measure] for entry in events if measure in entry]
        metrics[measure] = {
            "total": round(sum(values), 3),
            "median": median(values) if values else None,
            "observed": len(values),
        }
    return metrics


def summarize_run(directory):
    design_path = directory / "design.json"
    design = load(design_path)
    keys = [tuple(key) for key in design["cells"]]
    if len(set(keys)) != len(keys):
        raise ValueError("Design repeats an identical task, requirement, toolchain and repeat")
    rows = [
        run_cell(
            directory / f"{task}--{requirement}--{toolchain}--r{rep}",
            (task, requirement, toolchain, rep),
            bool(design.get("review_rounds")),
        )
        for task, requirement, toolchain, rep in sorted(keys)
    ]
    timelines = [row["timeline"] for row in rows if "timeline" in row]
    complete = [e for e in timelines if e["complete_scores"]]
    gaps = [
        e["seconds_function_to_qualified"]
        for e in complete
        if e["seconds_function_to_qualified"] is not None
    ]
    paired_events = [row["review"] for row in rows if "review" in row]
    started_qualified = [
        event for event in paired_events if event["first_candidate_outcome"] == "qualified"
    ]
    conditions = grouped(rows, ("requirement", "toolchain"))
    c_conditions = {x["toolchain"]: x for x in conditions if x["requirement"] == "c_required"}
    primary_delta = None
    if set(c_conditions) == {"ready", "setup"}:
        a, b = [c_conditions[k]["definite_miss_fraction"] for k in ("ready", "setup")]
        if a is not None and b is not None:
            primary_delta = (b - a) * 100
    return {
        "directory": directory.as_posix(),
        "design": witness(design_path),
        "model_config": design.get("model"),
        "served_models": sorted({row["served_model"] for row in rows if row.get("served_model")}),
        "totals": tally(rows),
        "conditions": conditions,
        "conditions_by_task": grouped(rows, ("task", "requirement", "toolchain")),
        "required_c_setup_minus_ready_pp": primary_delta,
        "statuses": dict(Counter(row["status"] for row in rows if "status" in row)),
        "timelines": {
            "available": len(timelines),
            "complete_scores": len(complete),
            "no_first_candidate": sum(not e["first_candidate_present"] for e in timelines),
            "function_seen": sum(e["first_function_pass"] is not None for e in complete),
            "qualification_seen": sum(e["first_qualified"] is not None for e in complete),
            "median_seconds_function_to_qualified": median(gaps) if gaps else None,
            "paired_times": len(gaps),
        },
        "review": {
            "enabled": bool(design.get("review_rounds")),
            "pairs": len(paired_events),
            "transitions": dict(Counter(event["transition"] for event in paired_events)),
            "full_token_reporting": sum(
                event["token_reporting_complete"] for event in paired_events
            ),
            "cost": cost_metrics(paired_events),
            "started_qualified": len(started_qualified),
            "cost_after_qualified_candidate": cost_metrics(started_qualified),
        },
        "cells": rows,
    }


def link(record, label):
    return f"[{label}](<{record['file']}>)"


def render(report):
    lines = ["# 终端任务交付要求与复查实验", ""]
    if history := report["historical_cases"]:
        fix = history["repair"]
        same = history["unmodified_review"]
        extra = same["additional_review"]
        lines += [
            "## 复用的历史案例",
            "",
            "两条记录来自已有的 TB2.1 正则任务，作为预先观察到的个案。",
            "",
            f"- **有效修复。** 初版和终版的 SHA-256 均与记录一致，"
            f"本地重跑已保存反例得到 {len(fix['initial_counterexample_matches'])} → "
            f"{len(fix['final_counterexample_matches'])} 个匹配。"
            f"历史官方终版得分为 {fix['official_final_reward']:g}，初版官方得分缺失。"
            f" {link(fix['evidence'][0], '原核验记录')}",
            f"- **追加复查后文件未变。** 历史核验记录给出 {extra['calls']} 次追加模型调用，"
            f"{extra['output_tokens']:,} 个输出 token，耗时 {same['additional_seconds']:.1f} 秒。"
            f"历史官方终版得分为 {same['official_final_reward']:g}。"
            f" {link(same['evidence'][0], '原核验记录')}",
            "",
        ]
    for run in report["runs"]:
        totals = run["totals"]
        lines += [
            f"## 本地实验批次 {Path(run['directory']).name}",
            "",
            f"收到 {totals['received']}/{totals['planned']} 个计划单元，"
            f"可用最终评分 {totals['valid_final']} 个。模型配置 `{run['model_config']}`。"
            f" {link(run['design'], '运行设计')}",
            "",
            "| 题目 | 要求 | 工具链 | 可用/计划 | 功能通过 | 两项都达标 | 明确缺交付 | 交付待确认 | 脚本 | 链路/评分异常 | 未出结果 |",
            "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for row in run["conditions"] + run["conditions_by_task"]:
            bad = row["pipeline_error"] + row["unscorable"]
            lines.append(
                f"| {row.get('task', '合计')} | {row['requirement']} | {row['toolchain']} | "
                f"{row['valid_final']}/{row['planned']} | {row['function_pass']} | "
                f"{row['qualified']} | {row['definite_requirement_miss']} | "
                f"{row['requirement_unresolved']} | {row['artifact_kinds'].get('script', 0)} | "
                f"{bad} | {row['pending']} |"
            )
        lines.append("")
        for row in run["conditions"]:
            if row["requirement"] != "c_required":
                continue
            lines.append(
                f"- 强制 C 的 `{row['toolchain']}` 组有 "
                f"{row['definite_requirement_miss']}/{row['valid_final']}。"
                f"这些试次功能通过，且明确缺交付要求。另有 "
                f"{row['requirement_unresolved']} 个功能通过但交付要求无法确认。"
            )
        if (delta := run["required_c_setup_minus_ready_pp"]) is not None:
            lines.append(f"- 需安装组减预装组的原始比例差为 {delta:+.1f} 个百分点。")
        lines += [
            "",
            "分母为该条件下有可用最终评分的运行。预算耗尽且已评分的运行计入，"
            "链路错误及最终评分不可用的运行单列。功能已通过时，重建结果不一致或超时记为交付待确认。",
            "",
        ]
        timeline, review = run["timelines"], run["review"]
        median_gap = timeline["median_seconds_function_to_qualified"]
        lines += [
            f"保存了 {timeline['available']} 条可分析时间线，其中 "
            f"{timeline['complete_scores']} 条每个已保存阶段有可用评分。"
            f"这批完整评分时间线中，{timeline['function_seen']} 条出现功能通过，"
            f"{timeline['qualification_seen']} 条出现功能与交付均达标。",
        ]
        if median_gap is not None:
            lines.append(
                f"两种通过均出现的 {timeline['paired_times']} 条时间线中，"
                f"首次功能通过到首次完整达标的中位间隔为 {median_gap:g} 秒。"
            )
        if review["enabled"]:
            transitions = review["transitions"]
            lines += [
                f"首份候选与最终提交可配对 {review['pairs']} 条。"
                f"从不达标改到达标 {transitions.get('improved', 0)} 条，"
                f"从达标改坏 {transitions.get('regressed', 0)} 条，"
                f"提交未变 {transitions.get('same_submission', 0)} 条，"
                f"提交改变但判定相同 {transitions.get('changed_same_outcome', 0)} 条，"
                f"证据不足 {transitions.get('unresolved', 0)} 条。"
                f"首份候选后共观测 {review['cost']['responses']['total']} 次模型响应和 "
                f"{review['cost']['tokens']['total']:,} 个 token，"
                f"{review['full_token_reporting']}/{review['pairs']} 条有完整的用量报告。",
                f"首份候选已经达标的 {review['started_qualified']} 条运行"
                f"后续共观测 {review['cost_after_qualified_candidate']['responses']['total']} "
                f"次响应和 {review['cost_after_qualified_candidate']['tokens']['total']:,} 个 token。",
            ]
        lines += [
            "",
            "| 试次 | 运行状态 | 最终判定 | 首次功能通过（秒） | 首次完整达标（秒） |",
            "|---|---|---|---:|---:|",
        ]
        for row in run["cells"]:
            timeline = row.get("timeline", {})
            function = (timeline.get("first_function_pass") or {}).get("seconds", "—")
            qualified = (timeline.get("first_qualified") or {}).get("seconds", "—")
            label = " / ".join(str(row[key]) for key in CELL_KEYS)
            if ref := row.get("result"):
                label = link(ref, label)
            lines.append(
                f"| {label} | {row.get('status', '—')} | {LABELS[row['outcome']]} | "
                f"{function} | {qualified} |"
            )
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="append", type=Path, default=[], help="Run output root")
    parser.add_argument("--out", type=Path, required=True, help="Directory for the two reports")
    parser.add_argument("--history", type=Path, default=HISTORY, help="Saved regex case directory")
    args = parser.parse_args()
    report = {
        "historical_cases": historical_cases(args.history.resolve()),
        "runs": [summarize_run(path.resolve()) for path in args.run],
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (args.out / "summary.md").write_text(render(report), encoding="utf-8")


if __name__ == "__main__":
    main()
