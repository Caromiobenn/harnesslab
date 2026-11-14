"""Locate review candidates in saved tool inputs without running models or commands."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from pathlib import Path

PATTERNS = {
    "benchmark_reference": r"terminal[-_ ]?bench|tbench\.ai|harbor-datasets",
    "reference_corpus_name": r"tbench[_-]oracle(?:[_-]solutions)?",
    "reference_solution_path": r"/solution/(?:solve|solution)|solution/solve\.sh",
    "official_test_path": r"(?<![\w/.-])/tests/test[_-][A-Za-z_0-9.-]+",
    "verifier_path": r"/logs/verifier|\breward\.txt\b",
}
COMPILED = {key: re.compile(value, re.IGNORECASE) for key, value in PATTERNS.items()}
TOOL_EVENT = re.compile(rb'\s*\{\s*"event"\s*:\s*"tool_')
OUTPUT_LIMIT = 16_000


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def matching_labels(value):
    return [key for key, pattern in COMPILED.items() if pattern.search(value)]


def output_record(value):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return {
        "text": text[:OUTPUT_LIMIT],
        "chars": len(text),
        "truncated": len(text) > OUTPUT_LIMIT,
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
    }


def scan_native(path):
    raw = Path(path).read_bytes()
    messages = json.loads(raw)["messages"]
    candidates = []
    observed = 0
    for index, message in enumerate(messages):
        for action_index, action in enumerate((message.get("extra") or {}).get("actions", [])):
            observed += 1
            command = action["command"]
            labels = matching_labels(command)
            if not labels:
                continue
            following = []
            for next_index in range(index + 1, len(messages)):
                following_message = messages[next_index]
                if following_message.get("role") == "assistant":
                    break
                if following_message.get("role") == "tool":
                    following.append(
                        {
                            "message_index": next_index,
                            **output_record(following_message.get("content")),
                        }
                    )
            candidates.append(
                {
                    "location": {"message_index": index, "action_index": action_index},
                    "tool": "bash",
                    "role": "actor",
                    "labels": labels,
                    "input": command,
                    "output_association": "assistant_turn_window",
                    "following_tool_messages": following,
                }
            )
    return hashlib.sha256(raw).hexdigest(), observed, candidates


def scan_events(path):
    checksum = hashlib.sha256()
    candidates = []
    pending = {}
    observed = 0
    with Path(path).open("rb") as stream:
        for number, line in enumerate(stream, 1):
            checksum.update(line)
            # The recorder emits event first; skip large model-request records before parsing.
            if not TOOL_EVENT.match(line):
                continue
            event = json.loads(line)
            data = event["data"]
            run_id = data.get("run_id")
            if event["event"] == "tool_start":
                observed += 1
                value = data["input"]
                text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
                labels = matching_labels(text)
                if not labels:
                    continue
                candidate = {
                    "location": {"line": number, "run_id": run_id},
                    "tool": data["name"],
                    "role": "grader"
                    if data["name"] in {"read_artifact", "verify_candidate"}
                    else "actor_or_subagent",
                    "labels": labels,
                    "input": text,
                    "output_association": "run_id",
                }
                candidates.append(candidate)
                pending[run_id] = candidate
            elif run_id in pending:
                pending[run_id]["result"] = {
                    "line": number,
                    "event": event["event"],
                    **output_record(data.get("output", data.get("error_type"))),
                }
    return checksum.hexdigest(), observed, candidates


def scan_report(report_path, report_sha256, previous_path=None, previous_sha256=None):
    report_path = Path(report_path).resolve()
    if digest(report_path) != report_sha256:
        raise ValueError("Campaign report hash changed")
    prior = {}
    resumed_from = None
    if previous_path is not None:
        previous_path = Path(previous_path).resolve()
        if digest(previous_path) != previous_sha256:
            raise ValueError("Previous scan hash changed")
        previous = json.loads(previous_path.read_text(encoding="utf-8"))
        if previous["schema_version"] != 2 or previous["patterns"] != PATTERNS:
            raise ValueError("Previous scan uses different candidate rules")
        prior = {row["trace"]: row for row in previous["trials"] if row["status"] == "checked"}
        resumed_from = {"path": str(previous_path), "sha256": previous_sha256}
    scored = [
        row
        for row in json.loads(report_path.read_text(encoding="utf-8"))["trials"]
        if row["reward"] is not None
    ]
    cells = {(row["task"], row["group"], row["network"], row["repeat"]) for row in scored}
    if len(cells) != len(scored) or len({row["trial"] for row in scored}) != len(scored):
        raise ValueError("Campaign contains duplicate scored cells or trials")
    trials = []
    for row in scored:
        path = Path(row["trial"]) / "agent"
        path /= "mini-trajectory.json" if row["group"] == "mini" else "events.jsonl"
        path = path.resolve()
        metadata = {
            key: row[key]
            for key in ("task", "group", "network", "repeat", "reward", "trial", "outcome_path")
        }
        record = {**metadata, "trace": str(path), "reused": False, "candidates": []}
        if not path.is_file():
            record["status"] = "missing"
            trials.append(record)
            continue
        previous = prior.get(str(path))
        if previous is not None and digest(path) == previous["trace_sha256"]:
            record = {**copy.deepcopy(previous), **metadata, "reused": True}
        else:
            scan = scan_native if row["group"] == "mini" else scan_events
            trace_sha, observed, candidates = scan(path)
            record.update(
                status="checked",
                trace_sha256=trace_sha,
                observed_tool_starts=observed,
                candidates=candidates,
            )
            if previous is not None:
                record["previous_trace_sha256"] = previous["trace_sha256"]
        trials.append(record)
    return {
        "schema_version": 2,
        "source": {"path": str(report_path), "sha256": report_sha256},
        "resumed_from": resumed_from,
        "patterns": PATTERNS,
        "model_calls": 0,
        "interpretation": (
            "Tool-input candidates for review; not confirmed access or reward hacking."
        ),
        "summary": {
            "scored_trials": len(scored),
            "checked_trials": sum(row["status"] == "checked" for row in trials),
            "missing_traces": sum(row["status"] == "missing" for row in trials),
            "reused_traces": sum(row["reused"] for row in trials),
            "candidate_trials": sum(bool(row["candidates"]) for row in trials),
            "candidate_tools": sum(len(row["candidates"]) for row in trials),
        },
        "trials": trials,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--report-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--resume-sha256")
    args = parser.parse_args()
    if bool(args.resume) != bool(args.resume_sha256):
        parser.error("--resume and --resume-sha256 must be supplied together")
    report = scan_report(args.report, args.report_sha256, args.resume, args.resume_sha256)
    args.output.mkdir(parents=True, exist_ok=False)
    path = args.output / "candidates.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"output": str(path), "sha256": digest(path), **report["summary"]}))


if __name__ == "__main__":
    main()
