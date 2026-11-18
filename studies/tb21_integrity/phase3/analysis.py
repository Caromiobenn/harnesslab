"""Analyze the planned paired WSL experiment using the last snapshot in each run."""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from statistics import median

ARMS = ("standard", "early_draft")
KEYS = ("workflow", "task", "requirement", "toolchain", "repeat")
EARLY_THRESHOLDS = (4, 8, 12)


def read_json(path):
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return None, "pending"
    try:
        return json.loads(data), None
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, "partial_json"


def first_qualified(event):
    return inspect_bool(event.get("score"), "qualified")


def inspect_bool(value, key):
    if not isinstance(value, dict):
        return None
    candidate = value.get(key)
    return candidate if type(candidate) is bool else None


def public_working(event):
    public = event.get("public")
    return (
        inspect_bool(public.get("checks"), "public_example") if isinstance(public, dict) else None
    )


def public_gate(event):
    trigger = inspect_bool(event.get("public"), "trigger_review")
    return None if trigger is None else not trigger


def event_point(event):
    return {key: event.get(key) for key in ("label", "responses", "tokens", "seconds", "digest")}


def locate_first(events, predicate):
    seen = [predicate(event) for event in events]
    first = next((event for event, accepted in zip(events, seen, strict=True) if accepted), None)
    if first is None:
        return {"event": None, "status": "verification_gap" if None in seen else "not_seen"}
    gap_before = any(value is None for value in seen[: events.index(first)])
    return {"event": event_point(first), "status": "at_or_before" if gap_before else "first_seen"}


def path_component(value):
    return isinstance(value, str) and value and not any(x in value for x in ("/", "\\", "..", "--"))


def plan_cells(design):
    if not isinstance(design, dict) or not isinstance(design.get("cells"), list):
        raise ValueError("Missing design cells")
    seen = set()
    for row in design["cells"]:
        if (
            not isinstance(row, list)
            or len(row) != 5
            or row[0] not in ARMS
            or not all(path_component(value) for value in row[1:4])
            or type(row[4]) is not int
            or row[4] <= 0
        ):
            raise ValueError(f"Malformed design cell: {row!r}")
        key = tuple(row)
        if key in seen:
            raise ValueError(f"Duplicate design cell: {row!r}")
        seen.add(key)
    if not seen:
        raise ValueError("Design is empty")
    missing = {
        block: [arm for arm in ARMS if (arm, *block) not in seen]
        for block in {cell[1:] for cell in seen}
    }
    missing = {block: absent for block, absent in missing.items() if absent}
    if missing:
        raise ValueError(f"Unbalanced paired plan: {missing!r}")
    return sorted(seen)


def analyze_cell(root, cell):
    arm, task, requirement, toolchain, repeat = cell
    directory = root / arm / f"{task}--{requirement}--{toolchain}--r{repeat}"
    result_path, timeline_path = directory / "result.json", directory / "timeline.json"
    row = dict(zip(KEYS, cell, strict=True))
    row["directory"] = directory.as_posix()
    result, result_error = read_json(result_path)
    if result_error is not None:
        return {**row, "final_status": result_error}
    if not isinstance(result, dict) or any(
        result.get(key) != value for key, value in row.items() if key in KEYS
    ):
        return {**row, "final_status": "result_identity_error"}
    row["status"] = result.get("status")
    metrics = result.get("metrics")
    row["metrics"] = metrics if isinstance(metrics, dict) else {}
    events, timeline_error = read_json(timeline_path)
    if timeline_error is not None:
        return {**row, "final_status": "timeline_" + timeline_error}
    if (
        not isinstance(events, list)
        or not events
        or not all(isinstance(item, dict) for item in events)
        or events[-1].get("label") != "final"
    ):
        return {**row, "final_status": "incomplete_timeline"}
    end = events[-1]
    row["final_snapshot"] = event_point(end)
    row["final_public_working"] = public_working(end)
    row["final_public_gate_pass"] = public_gate(end)
    row["first_public_working"] = locate_first(events, public_working)
    row["first_public_gate_pass"] = locate_first(events, public_gate)
    row["first_qualified"] = locate_first(events, first_qualified)
    row["natural_final"] = any(event.get("label") == "first_candidate" for event in events)
    drafts = [event for event in events if event.get("label") == "draft"]
    row["drafts"] = [
        {
            **event_point(event),
            "public_working": public_working(event),
            "public_gate_pass": public_gate(event),
            "qualified": first_qualified(event),
        }
        for event in drafts
    ]
    if result.get("status") == "pipeline_error":
        return {**row, "final_status": "pipeline_error"}
    qualified = first_qualified(end)
    if qualified is None:
        return {**row, "final_status": "unscored_end"}
    if "score" in result and result["score"] != end["score"]:
        return {**row, "final_status": "end_score_mismatch"}
    return {**row, "final_status": "valid", "qualified": qualified}


def known_tokens(row):
    raw = row.get("metrics", {}).get("total_tokens")
    return raw if type(raw) is int and raw >= 0 else None


def numeric_summary(values):
    return {"observed": len(values), "median": median(values) if values else None}


def first_outcomes(rows, field):
    timelines = [row[field] for row in rows if field in row]
    points = [entry["event"] for entry in timelines if entry["event"] is not None]
    timing = Counter(entry["status"] for entry in timelines)
    cost = [point["tokens"] for point in points if type(point["tokens"]) is int]
    responses = [point["responses"] for point in points if type(point["responses"]) is int]
    return {
        "timelines": len(timelines),
        "seen": len(points),
        "not_seen_at_end": timing["not_seen"],
        "missing_timeline": len(rows) - len(timelines),
        "verification_gap": timing["verification_gap"],
        "timing_upper_bound": timing["at_or_before"],
        "by_response": {str(t): sum(value <= t for value in responses) for t in EARLY_THRESHOLDS},
        "responses": numeric_summary(responses),
        "tokens": numeric_summary(cost),
    }


def arm_summary(rows):
    valid = [row for row in rows if row["final_status"] == "valid"]
    successes = sum(row["qualified"] for row in valid)
    usable_tokens = [value for row in rows if (value := known_tokens(row)) is not None]
    drafts = [event for row in rows for event in row.get("drafts", ())]
    retained = [row for row in rows if "natural_final" in row]
    draft_changes = Counter()
    for row in valid:
        accepted = next((x for x in row["drafts"] if x["public_working"] is True), None)
        if accepted is None or accepted["qualified"] is None:
            continue
        before, after = accepted["qualified"], row["qualified"]
        draft_changes[
            "qualified_unchanged"
            if before and after
            else "unqualified_unchanged"
            if not before and not after
            else "repaired"
            if after
            else "regressed"
        ] += 1
    return {
        "planned": len(rows),
        "valid_finals": len(valid),
        "qualified": successes,
        "final_qualification_rate": successes / len(valid) if valid else None,
        "final_statuses": dict(Counter(row["final_status"] for row in rows)),
        "stop_reasons": dict(
            Counter(row["status"] for row in rows if row.get("status") is not None)
        ),
        "cost": {
            **numeric_summary(usable_tokens),
            "total": sum(usable_tokens),
            "per_qualified": sum(usable_tokens) / successes
            if successes and usable_tokens
            else None,
        },
        "natural_final": sum(row["natural_final"] for row in retained),
        "timelines": len(retained),
        "runs_with_any_draft": sum(bool(row.get("drafts")) for row in retained),
        "runs_with_accepted_draft": sum(
            any(e["public_working"] is True for e in row["drafts"]) for row in retained
        ),
        "draft_events": len(drafts),
        "accepted_draft_events": sum(event["public_working"] is True for event in drafts),
        "unknown_draft_events": sum(event["public_working"] is None for event in drafts),
        "first_public_draft_to_final": dict(draft_changes),
        "first_public_working": first_outcomes(rows, "first_public_working"),
        "first_public_gate_pass": first_outcomes(rows, "first_public_gate_pass"),
        "first_qualified": first_outcomes(rows, "first_qualified"),
        "public_working_but_final_failed": sum(
            row["final_public_working"] is True and not row["qualified"] for row in valid
        ),
        "public_gate_passed_but_final_failed": sum(
            row["final_public_gate_pass"] is True and not row["qualified"] for row in valid
        ),
    }


def pp(left, right):
    return round(100 * (left - right), 6) if left is not None and right is not None else None


def block_outcomes(rows):
    by_block = {}
    for row in rows:
        block = tuple(row[key] for key in KEYS[1:])
        by_block.setdefault(block, {})[row["workflow"]] = row
    detail = []
    for block, arms in sorted(by_block.items()):
        one, two = (arms[arm] for arm in ARMS)
        issues = {
            arm: candidate["final_status"]
            for arm, candidate in arms.items()
            if candidate["final_status"] != "valid"
        }
        a, b = one.get("qualified"), two.get("qualified")
        if issues:
            result = "incomplete"
        elif a == b:
            result = "both_qualified" if a else "both_failed"
        else:
            result = "early_draft_only" if b else "standard_only"
        tokens = [known_tokens(arms[arm]) for arm in ARMS]
        detail.append(
            {
                **dict(zip(KEYS[1:], block, strict=True)),
                "outcome": result,
                "incomplete_reasons": issues,
                "recorded_token_delta_early_minus_standard": (
                    tokens[1] - tokens[0] if None not in tokens and not issues else None
                ),
            }
        )
    counts = Counter(item["outcome"] for item in detail)
    complete = len(detail) - counts["incomplete"]
    comparable_tokens = [
        pair["recorded_token_delta_early_minus_standard"]
        for pair in detail
        if pair["recorded_token_delta_early_minus_standard"] is not None
    ]
    return {
        "planned": len(detail),
        "complete": complete,
        "joint_outcomes": {
            key: counts[key]
            for key in (
                "both_qualified",
                "both_failed",
                "early_draft_only",
                "standard_only",
                "incomplete",
            )
        },
        "qualification_delta_early_minus_standard_pp": (
            round(100 * (counts["early_draft_only"] - counts["standard_only"]) / complete, 6)
            if complete
            else None
        ),
        "recorded_token_delta_early_minus_standard": numeric_summary(comparable_tokens),
        "blocks": detail,
    }


def analyze(root):
    path = root / "design.json"
    design, error = read_json(path)
    if error is not None:
        raise ValueError(f"Could not read study design ({error}): {path}")
    rows = [analyze_cell(root, cell) for cell in plan_cells(design)]
    arms = {arm: arm_summary([row for row in rows if row["workflow"] == arm]) for arm in ARMS}
    return {
        "run": root.as_posix(),
        "design_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "by_arm": arms,
        "unpaired_qualification_delta_early_minus_standard_pp": pp(
            arms["early_draft"]["final_qualification_rate"],
            arms["standard"]["final_qualification_rate"],
        ),
        "matched": block_outcomes(rows),
        "by_task_and_arm": {
            task: {
                arm: arm_summary(
                    [row for row in rows if row["workflow"] == arm and row["task"] == task]
                )
                for arm in ARMS
            }
            for task in sorted({row["task"] for row in rows})
        },
        "cells": rows,
    }


def fmt(number, decimals=0):
    return "—" if number is None else f"{number:,.{decimals}f}"


def signed(number):
    return "—" if number is None else f"{number:+.1f}"


def markdown(data):
    arms, paired = data["by_arm"], data["matched"]
    lines = [
        "# 首次交卷工作流对照",
        "",
        "终版判定采用每条轨迹最后一个快照。提前交卷标记的接受依据是独立运行公开样例。",
        "交付格式等附加要求由完整的公开检查单记录。正式功能判分还使用独立的私有输入。",
        "",
        "| 工作流 | 有效终版 / 计划 | 终版达标 | 记录 token 总计 | 单次中位 | 每份合格提交 token |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for arm in ARMS:
        row = arms[arm]
        cost = row["cost"]
        lines.append(
            f"| {arm} | {row['valid_finals']}/{row['planned']} | "
            f"{row['qualified']}/{row['valid_finals']} | {fmt(cost['total'])} "
            f"（{cost['observed']} 次） | {fmt(cost['median'])} | {fmt(cost['per_qualified'])} |"
        )
    joint = paired["joint_outcomes"]
    lines += [
        "",
        f"按任务、要求、工具链和重复编号配对，完整配对 {paired['complete']}/{paired['planned']}。"
        f"两组都达标 {joint['both_qualified']} 对、都失败 {joint['both_failed']} 对、"
        f"仅提前交卷达标 {joint['early_draft_only']} 对、"
        f"仅标准组达标 {joint['standard_only']} 对。",
        f"提前交卷组减标准组的未配对差为 "
        f"{signed(data['unpaired_qualification_delta_early_minus_standard_pp'])} 个百分点，"
        f"同条件配对差为 "
        f"{signed(paired['qualification_delta_early_minus_standard_pp'])} 个百分点。",
        f"完整可比的 {paired['recorded_token_delta_early_minus_standard']['observed']} 对中，"
        f"提前交卷组每对的 token 差的中位数为 "
        f"{fmt(paired['recorded_token_delta_early_minus_standard']['median'])}。",
        "",
        "| 工作流 | 可用时间线 | 第 4 次前 / 第 8 次前 / 第 12 次前首次通过公开样例¹ | "
        "首次公开通过 token 中位 | 到结束未观察到通过 | 首次通过完整公开检查 | 曾私下达标 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for arm, row in arms.items():
        public = row["first_public_working"]
        at = " / ".join(
            str(public["by_response"][str(threshold)]) for threshold in EARLY_THRESHOLDS
        )
        lines.append(
            f"| {arm} | {public['timelines']} | {at} | {fmt(public['tokens']['median'])} "
            f"（{public['tokens']['observed']} 次） | {public['not_seen_at_end']} | "
            f"{row['first_public_gate_pass']['seen']} | {row['first_qualified']['seen']} |"
        )
    lines += [
        "",
        "¹ 含本次响应产生的快照。首次通过 token 的中位数只用观察到公开样例通过的运行。"
        "每次运行在结束时封存，累计预算内未出现通过的独立计数。"
        "缺失时间线、验证缺口和可能更早通过的记录可在 JSON 中查看。",
        "",
        "| 工作流 | 自然交卷 | 声明过草稿 | 至少一次草稿被接受 | "
        "终版公开样例通过但私下失败 | 终版公开检查全过但私下失败 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for arm, row in arms.items():
        lines.append(
            f"| {arm} | {row['natural_final']}/{row['timelines']} | {row['runs_with_any_draft']} | "
            f"{row['runs_with_accepted_draft']} | {row['public_working_but_final_failed']} | "
            f"{row['public_gate_passed_but_final_failed']} |"
        )
    lines += [
        "",
        "每组 token 合计覆盖有记录的所有尝试，包括解题失败。"
        "配对 token 差只使用双方终版可评分且用量可读的组合。"
        "终版不达标仍计入有效尝试。草稿接受数按公开样例检查处理。",
        "",
        "| 工作流 | 最终记录状态 | 运行停止原因 |",
        "| --- | --- | --- |",
    ]
    for arm, row in arms.items():
        statuses = ", ".join(
            f"{key} {value}" for key, value in sorted(row["final_statuses"].items())
        )
        reasons = ", ".join(f"{key} {value}" for key, value in sorted(row["stop_reasons"].items()))
        lines.append(f"| {arm} | {statuses or '—'} | {reasons or '—'} |")
    lines += [
        "",
        "| 未完整配对的条件 | 原因 |",
        "| --- | --- |",
    ]
    for block in paired["blocks"]:
        if block["incomplete_reasons"]:
            key = " / ".join(str(block[field]) for field in KEYS[1:])
            why = ", ".join(
                f"{arm} {reason}" for arm, reason in block["incomplete_reasons"].items()
            )
            lines.append(f"| {key} | {why} |")
    if paired["complete"] == paired["planned"]:
        lines.append("| 无 | — |")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    data = analyze(args.run.resolve())
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.out / "summary.md").write_text(markdown(data), encoding="utf-8")


if __name__ == "__main__":
    main()
