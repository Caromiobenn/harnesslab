"""Analyze saved qualification scores and simulate three delivery policies on shared traces."""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from statistics import median

STUDY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(STUDY))
import summarize as base

POLICIES = ("emit", "fixed_review", "public_gate")
POLICY_LABELS = {"emit": "直接提交", "fixed_review": "固定复查", "public_gate": "公开检查触发复查"}
VALID = base.OUTCOMES[:4]


def token_cost(event, usage_complete):
    if not usage_complete:
        return None
    return nonnegative(event.get("tokens"))


def nonnegative(value):
    if type(value) in (int, float) and value >= 0:
        return value
    return None


def run_folder(run, row):
    task, requirement, toolchain, rep = (row[key] for key in base.CELL_KEYS)
    return run / f"{task}--{requirement}--{toolchain}--r{rep}"


def trace_ref(folder):
    path = folder / "trajectory.jsonl"
    return base.witness(path) if path.is_file() else None


def gate_data(trial):
    gate = trial.get("public_gate")
    if isinstance(gate, dict) and isinstance(gate.get("trigger_review"), bool):
        if (
            gate.get("error")
            or gate.get("technical_error")
            or gate.get("status")
            in {
                "error",
                "technical_error",
            }
        ):
            return None
        return gate
    return None


def pair(run, row):
    if row["outcome"] in {"pending", "pipeline_error", "unscorable"}:
        return None, row["outcome"]
    folder = run_folder(run, row)
    if not (folder / "timeline.json").is_file():
        return None, "missing_timeline"
    events = base.load(folder / "timeline.json")
    first = next((e for e in events if e.get("label") == "first_candidate"), None)
    final = next((e for e in reversed(events) if e.get("label") == "final"), None)
    if first is None:
        return None, "no_first_candidate"
    if final is None:
        return None, "no_final_checkpoint"
    first_score = base.outcome(first.get("score", {}))
    final_score = base.outcome(final.get("score", {}))
    if first_score not in VALID or final_score not in VALID or final_score != row["outcome"]:
        return None, "invalid_checkpoint_score"
    gate = gate_data(base.load(folder / "result.json"))
    if gate is None:
        return None, "invalid_public_gate"
    triggered = gate["trigger_review"]
    complete_usage = isinstance(row["metrics"].get("usage_reported"), int) and row["metrics"][
        "usage_reported"
    ] == row["metrics"].get("model_responses")
    first_tokens, final_tokens = [token_cost(e, complete_usage) for e in (first, final)]
    if first_tokens is not None and final_tokens is not None and first_tokens > final_tokens:
        first_tokens = final_tokens = None
    if first_tokens is None or final_tokens is None:
        first_tokens = final_tokens = None
    first_seconds, final_seconds = [nonnegative(e.get("seconds")) for e in (first, final)]
    gate_seconds = nonnegative(gate.get("seconds"))
    gated_seconds = None
    if None not in (first_seconds, final_seconds, gate_seconds) and final_seconds >= first_seconds:
        gated_seconds = (final_seconds if triggered else first_seconds) + gate_seconds
    else:
        first_seconds = final_seconds = None
    return {
        **{key: row[key] for key in base.CELL_KEYS},
        "state_change": base.transition(first, final),
        "first": first_score,
        "final": final_score,
        "first_digest": first.get("digest"),
        "final_digest": final.get("digest"),
        "gate": gate,
        "policy_outcomes": dict(
            zip(
                POLICIES,
                (
                    first_score,
                    final_score,
                    final_score if triggered else first_score,
                ),
                strict=True,
            )
        ),
        "policy_tokens": dict(
            zip(
                POLICIES,
                (
                    first_tokens,
                    final_tokens,
                    final_tokens if triggered else first_tokens,
                ),
                strict=True,
            )
        ),
        "policy_seconds": dict(
            zip(
                POLICIES,
                (
                    first_seconds,
                    final_seconds,
                    gated_seconds,
                ),
                strict=True,
            )
        ),
        "first_responses": first.get("responses"),
        "final_responses": final.get("responses"),
        "first_seconds": first.get("seconds"),
        "final_seconds": final.get("seconds"),
        "result": row["result"],
        "timeline": base.witness(folder / "timeline.json"),
    }, None


def summarize_policy(pairs, name):
    counted = Counter(p["policy_outcomes"][name] for p in pairs)
    tokens = [p["policy_tokens"][name] for p in pairs if p["policy_tokens"][name] is not None]
    seconds = [p["policy_seconds"][name] for p in pairs if p["policy_seconds"][name] is not None]
    fixes = sum(
        p["first"] in {"function_failed", "definite_requirement_miss"}
        and p["policy_outcomes"][name] == "qualified"
        for p in pairs
    )
    regressions = sum(
        p["first"] == "qualified"
        and p["policy_outcomes"][name] in {"function_failed", "definite_requirement_miss"}
        for p in pairs
    )
    return {
        "denominator": len(pairs),
        "qualified": counted["qualified"],
        "qualification_unresolved": counted["requirement_unresolved"],
        "definite_requirement_miss": counted["definite_requirement_miss"],
        "function_failed": counted["function_failed"],
        "repairs": fixes,
        "regressions": regressions,
        "tokens_total": sum(tokens) if tokens else None,
        "tokens_median": median(tokens) if tokens else None,
        "tokens_denominator": len(tokens),
        "seconds_median": median(seconds) if seconds else None,
        "seconds_denominator": len(seconds),
    }


def cases(run, pairs):
    groups = {
        "repair": [],
        "regression": [],
        "correct_unchanged": [],
        "repair_skipped_by_gate": [],
        "regression_avoided_by_gate": [],
    }
    for p in pairs:
        change, triggered = p["state_change"], p["gate"]["trigger_review"]
        names = []
        if change == "improved":
            names.append("repair")
            if not triggered:
                names.append("repair_skipped_by_gate")
        if change == "regressed":
            names.append("regression")
            if not triggered:
                names.append("regression_avoided_by_gate")
        if change == "same_submission" and p["first"] == "qualified":
            names.append("correct_unchanged")
        if not names:
            continue
        trace = trace_ref(run_folder(run, p))
        if trace:
            reference = {
                **{key: p[key] for key in base.CELL_KEYS},
                "result": p["result"],
                "timeline": p["timeline"],
                "trajectory": trace,
            }
            for name in names:
                groups[name].append(reference)
    return groups


def inspect_run(directory, calibration=False):
    summary = base.summarize_run(directory)
    if calibration:
        return summary
    pairs, excluded = [], Counter()
    for row in summary["cells"]:
        pair_row, why = pair(directory, row)
        if why:
            excluded[why] += 1
        else:
            pairs.append(pair_row)
    gate_times = [t for p in pairs if (t := nonnegative(p["gate"].get("seconds"))) is not None]
    policies = {name: summarize_policy(pairs, name) for name in POLICIES}
    fixed_cost = policies["fixed_review"]["tokens_total"]
    gated_cost = policies["public_gate"]["tokens_total"]
    summary["delivery"] = {
        "paired": len(pairs),
        "excluded": dict(excluded),
        "review_triggered": sum(p["gate"]["trigger_review"] for p in pairs),
        "public_gate_seconds": {
            "total": sum(gate_times) if gate_times else None,
            "median": median(gate_times) if gate_times else None,
            "observed": len(gate_times),
        },
        "policies": policies,
        "gated_tokens_saved_vs_fixed": fixed_cost - gated_cost if fixed_cost is not None else None,
        "by_condition": [
            {
                "requirement": requirement,
                "toolchain": toolchain,
                "policies": {
                    name: summarize_policy(
                        [
                            p
                            for p in pairs
                            if (p["requirement"], p["toolchain"]) == (requirement, toolchain)
                        ],
                        name,
                    )
                    for name in POLICIES
                },
            }
            for requirement, toolchain in sorted(
                {(p["requirement"], p["toolchain"]) for p in pairs}
            )
        ],
        "pairs": pairs,
        "cases_with_traces": cases(directory, pairs),
    }
    return summary


def report_text(calibration, formal):
    lines = ["# 第二阶段实验汇总", ""]
    if calibration is not None:
        totals = calibration["totals"]
        lines += [
            "## 校准批次",
            "",
            f"收到 {totals['received']}/{totals['planned']} 个计划单元，"
            f"{totals['valid_final']} 个有可用评分，{totals['qualified']} 个达到交付要求。"
            f" {base.link(calibration['design'], '校准设计')}",
            "",
            "| 题目 | 交付要求 | 最终判定 | 运行状态 |",
            "|---|---|---|---|",
        ]
        for row in calibration["cells"]:
            name = row["task"]
            if ref := row.get("result"):
                name = base.link(ref, name)
            lines.append(
                f"| {name} | {row['requirement']} | {base.LABELS[row['outcome']]} | "
                f"{row.get('status', '—')} |"
            )
        lines.append("")
    if formal is None:
        return "\n".join(lines).strip() + "\n"
    lines += [base.render({"historical_cases": None, "runs": [formal]}).split("\n\n", 1)[1], ""]
    delivery = formal["delivery"]
    lines += [
        "## 三种交付策略的同轨迹比较",
        "",
        f"共有 {delivery['paired']}/{formal['totals']['planned']} 个计划单元满足配对条件。"
        f"公开检查在其中 {delivery['review_triggered']} 个判断需要复查。"
        "每个策略都从同一次运行保留下来的首份候选或终版选取产物，复查本身使用原运行记录。",
        "",
        "| 策略 | 达标/配对 | 交付待确认 | 明确缺交付 | 功能未过 | 修复 | 回归 | 总 token | 完整用量配对 | 耗时中位数（秒） |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, p in delivery["policies"].items():
        tokens = "—" if p["tokens_total"] is None else f"{p['tokens_total']:,}"
        elapsed = "—" if p["seconds_median"] is None else f"{p['seconds_median']:.2f}"
        lines.append(
            f"| {POLICY_LABELS[name]} | {p['qualified']}/{p['denominator']} | "
            f"{p['qualification_unresolved']} | {p['definite_requirement_miss']} | "
            f"{p['function_failed']} | {p['repairs']} | {p['regressions']} | {tokens} | "
            f"{p['tokens_denominator']} | {elapsed} |"
        )
    lines += [
        "",
        "配对需要首份候选、最终评分和有效公开检查。修复与回归只计入两侧判定明确的变化。"
        "各策略的 token 合计使用同一批用量完整的配对。"
        "触发策略的耗时是假设检查顺序执行，将实测检查耗时与所选交付节点的耗时相加。",
    ]
    times = delivery["public_gate_seconds"]
    if times["observed"]:
        lines.append(
            f"公开检查本身在 {times['observed']} 条记录中耗时中位数为 {times['median']:.3f} 秒。"
        )
    if (saved := delivery["gated_tokens_saved_vs_fixed"]) is not None:
        lines.append(f"同一批完整用量配对上，公开检查触发策略比固定复查少用 {saved:,} 个 token。")
    if delivery["excluded"]:
        lines += ["", "未配对的情况", ""]
        lines.extend(
            f"- `{reason}` 共 {count} 个" for reason, count in delivery["excluded"].items()
        )
    named_cases = delivery["cases_with_traces"]
    if any(named_cases.values()):
        lines += ["", "可回看轨迹的案例", ""]
        labels = {
            "repair": "复查修复",
            "regression": "复查回归",
            "correct_unchanged": "达标后提交未变",
            "repair_skipped_by_gate": "公开检查未触发这次有效复查",
            "regression_avoided_by_gate": "公开检查可避免这次复查回归",
        }
        for key, records in named_cases.items():
            for record in records[:2]:
                cell = " / ".join(str(record[name]) for name in base.CELL_KEYS)
                lines.append(
                    f"- {labels[key]}。{cell}。"
                    f" {base.link(record['trajectory'], '轨迹')} · "
                    f"{base.link(record['timeline'], '判分时间线')}"
                )
    return "\n".join(lines).strip() + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path)
    parser.add_argument("--calibration", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if not (args.run or args.calibration):
        parser.error("supply --run, --calibration, or both")
    calibration = inspect_run(args.calibration.resolve(), True) if args.calibration else None
    formal = inspect_run(args.run.resolve()) if args.run else None
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.json").write_text(
        json.dumps(
            {
                "calibration": calibration,
                "formal": formal,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (args.out / "summary.md").write_text(report_text(calibration, formal), encoding="utf-8")


if __name__ == "__main__":
    main()
