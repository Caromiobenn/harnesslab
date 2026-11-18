"""Summarize terminal trials with no first candidate without exporting their raw traces."""

import argparse
import hashlib
import json
import os
import re
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ARTIFACTS = HERE.parents[1] / "phase2" / "artifacts"
DEFAULT_MATRIX = ARTIFACTS / "accepted-matrix-20261118"
DEFAULT_SUMMARY = ARTIFACTS / "final-summary" / "summary.json"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def file_ref(path, root):
    return {
        "file": path.relative_to(root).as_posix(),
        "sha256": digest(path.read_bytes()),
    }


def first_response(events, predicate):
    return next((e for e in events if predicate(e)), None)


def tool_steps(path):
    replies, calls = [], []
    known = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if response := event.get("response"):
            choice = response["choices"][0]
            replies.append(choice["finish_reason"])
            for tool in choice["message"].get("tool_calls") or []:
                command = json.loads(tool["function"]["arguments"])["command"]
                call = {
                    "response": len(replies),
                    "command_sha256": digest(command.encode()),
                    "outcome": None,
                    "mismatch_marker": False,
                }
                calls.append(call)
                known[tool["id"]] = call
        if event.get("role") == "tool":
            call = known[event["tool_call_id"]]
            output = event["content"]
            call["outcome"] = output.partition("\n")[0]
            call["mismatch_marker"] = bool(re.search(r"(?m)^(MISMATCH|DIFF)\b", output))
    return Counter(replies), calls


def snapshot_digest(event, folder):
    manifest = event["files"]
    recorded = event["digest"]
    if digest(json.dumps(manifest, sort_keys=True).encode()) != recorded:
        raise ValueError(f"snapshot manifest hash mismatch in {folder.name}")
    checked = 0
    missing = 0
    for name, entry in manifest.items():
        if entry is None:
            continue
        expected_sha, _ = entry
        snapshot = folder / "snapshots" / recorded / name
        if not snapshot.is_file():
            missing += 1
            continue
        if digest(snapshot.read_bytes()) != expected_sha:
            raise ValueError(f"snapshot content hash mismatch in {folder.name}")
        checked += 1
    return checked, missing


def read_case(folder, result, events, root):
    final = events[-1]
    if final["label"] != "final" or final["score"] != result["score"]:
        raise ValueError(f"final score mismatch in {folder.name}")
    visited = set()
    checked = missing = 0
    for checkpoint in events:
        if checkpoint["digest"] not in visited:
            with_bytes, without_bytes = snapshot_digest(checkpoint, folder)
            checked += with_bytes
            missing += without_bytes
            visited.add(checkpoint["digest"])
    first_executable = first_response(
        events, lambda e: (e["files"].get("solution") or [None, False])[1]
    )
    first_correct = first_response(events, lambda e: e["score"]["function_checks"]["passed"] > 0)
    first_qualified = first_response(events, lambda e: e["score"]["qualified"])
    last_change = next(e for e in reversed(events[:-1]) if e["label"] == "tool")
    stops, steps = tool_steps(folder / "trajectory.jsonl")
    final_checks = result["score"]["function_checks"]
    final_sha = steps[-1]["command_sha256"]
    suffix = next(
        (i for i, step in enumerate(reversed(steps)) if step["command_sha256"] != final_sha),
        len(steps),
    )

    def checkpoint(event):
        if event is None:
            return None
        return {name: event[name] for name in ("responses", "seconds", "digest")}

    refs = [
        file_ref(folder / name, root)
        for name in ("result.json", "timeline.json", "trajectory.jsonl")
    ]
    return {
        "case": folder.name,
        "actor_status": result["status"],
        "finish_reasons": stops,
        "response_count": sum(stops.values()),
        "tool_calls": len(steps),
        "last_exit": steps[-1]["outcome"],
        "first_executable": checkpoint(first_executable),
        "first_correct_hidden_case": checkpoint(first_correct),
        "first_qualified": checkpoint(first_qualified),
        "last_deliverable_change": checkpoint(last_change),
        "final_qualified": result["score"]["qualified"],
        "final_artifact_kind": result["score"]["artifact_kind"],
        "final_hidden_passed": final_checks["passed"],
        "final_hidden_total": final_checks["total"],
        "final_hidden_outcomes": Counter(final_checks["outcomes"]),
        "final_artifact_digest": final["digest"],
        "post_qualification_unchanged": first_qualified["digest"] == final["digest"]
        if first_qualified
        else None,
        "post_qualification_tokens": final["tokens"] - first_qualified["tokens"]
        if first_qualified
        else None,
        "post_qualification_responses": final["responses"] - first_qualified["responses"]
        if first_qualified
        else None,
        "post_qualification_tool_calls": final["tool_calls"] - first_qualified["tool_calls"]
        if first_qualified
        else None,
        "first_mismatch_marker_response": next(
            (s["response"] for s in steps if s["mismatch_marker"]), None
        ),
        "final_identical_command_streak": suffix,
        "final_command_sha256": final_sha,
        "distinct_commands": len({s["command_sha256"] for s in steps}),
        "snapshot_hashes": {"checked": checked, "snapshot_file_not_copied": missing},
        "source_files": refs,
    }


def analyze(matrix, summary):
    common = Path(os.path.commonpath((matrix, summary)))
    design = load(matrix / "design.json")
    cases = []
    for task, requirement, toolchain, repeat in sorted(design["cells"]):
        folder = matrix / f"{task}--{requirement}--{toolchain}--r{repeat}"
        result, timeline = [load(folder / name) for name in ("result.json", "timeline.json")]
        if any(e["label"] == "first_candidate" for e in timeline):
            continue
        cases.append(read_case(folder, result, timeline, common))
    coverage = load(summary)["formal"]["timelines"]
    if coverage["no_first_candidate"] != len(cases) or coverage["available"] != len(
        design["cells"]
    ):
        raise ValueError("formal summary and accepted matrix disagree")
    totals = {
        "planned": len(design["cells"]),
        "no_first_candidate": len(cases),
        "with_executable": sum(c["first_executable"] is not None for c in cases),
        "passing_at_least_one_hidden_case": sum(
            c["first_correct_hidden_case"] is not None for c in cases
        ),
        "qualified_at_some_point": sum(c["first_qualified"] is not None for c in cases),
        "qualified_at_first_executable": sum(
            c["first_executable"] is not None and c["first_executable"] == c["first_qualified"]
            for c in cases
        ),
        "final_qualified": sum(c["final_qualified"] for c in cases),
        "tool_calls_are_only_finish_reason": sum(
            set(c["finish_reasons"]) == {"tool_calls"} for c in cases
        ),
        "last_tool_exit_zero": sum(c["last_exit"] == "exit=0" for c in cases),
        "no_deliverable_change_last_five_responses": sum(
            c["last_deliverable_change"]["responses"] <= c["response_count"] - 5 for c in cases
        ),
        "consecutive_exact_repeat_last_command": sum(
            c["final_identical_command_streak"] >= 2 for c in cases
        ),
        "incorrect_with_model_test_mismatch_marker": sum(
            not c["final_qualified"] and c["first_mismatch_marker_response"] is not None
            for c in cases
        ),
        "after_first_qualified_observed_tokens": sum(
            c["post_qualification_tokens"] or 0 for c in cases
        ),
        "after_first_qualified_responses": sum(
            c["post_qualification_responses"] or 0 for c in cases
        ),
        "after_first_qualified_tool_calls": sum(
            c["post_qualification_tool_calls"] or 0 for c in cases
        ),
    }
    return {
        "source_root_name": common.name,
        "source_file_index": [
            file_ref(p, common)
            for p in (
                matrix / "design.json",
                matrix / "results.json",
                summary,
            )
        ],
        "totals": totals,
        "cases": cases,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--formal-summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--out", type=Path, default=HERE / "no-candidate.json")
    args = parser.parse_args()
    report = analyze(args.matrix.resolve(), args.formal_summary.resolve())
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["totals"]))


if __name__ == "__main__":
    main()
