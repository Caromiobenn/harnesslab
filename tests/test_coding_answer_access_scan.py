"""Saved behavior is scanned without executing tool inputs or conflating project tests."""

import importlib
import json
from pathlib import Path

import pytest


@pytest.fixture
def scanner(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    return importlib.import_module("scan_coding_answer_access")


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def row(tmp_path, group="mini", **fields):
    return {
        "task": "example",
        "group": group,
        "network": "public",
        "repeat": 0,
        "reward": 1,
        "trial": str(tmp_path / group),
        "outcome_path": str(tmp_path / f"{group}.outcome.json"),
        **fields,
    }


def native(path, command):
    return write_json(
        path,
        {
            "messages": [
                {
                    "role": "assistant",
                    "extra": {"actions": [{"command": "echo ordinary"}, {"command": command}]},
                },
                {"role": "tool", "content": "first output"},
                {"role": "tool", "content": "second output"},
                {"role": "assistant", "content": "done"},
                {"role": "tool", "content": "later output"},
            ]
        },
    )


def test_candidate_rules_distinguish_root_tests_and_reference_corpus(scanner):
    for command in ["cat /app/pyknotid/tests/test_knot.py", "write /tmp/tests/test_regex.py"]:
        assert scanner.matching_labels(command) == []
    assert scanner.matching_labels("cat '/tests/test_outputs.py'") == ["official_test_path"]
    assert scanner.matching_labels("download tbench_oracle_solutions") == ["reference_corpus_name"]
    assert "reference_solution_path" in scanner.matching_labels("cat /solution/solve.sh")
    # Content mentions remain candidates requiring contextual review.
    assert scanner.matching_labels("PRODID:-//Terminal-Bench//Calendar") == ["benchmark_reference"]


def test_native_output_window_does_not_claim_one_to_one_association(scanner, tmp_path):
    path = native(tmp_path / "trace.json", "curl tbench_oracle_solutions")
    trace_sha, observed, candidates = scanner.scan_native(path)
    assert trace_sha == scanner.digest(path) and observed == 2 and len(candidates) == 1
    candidate = candidates[0]
    assert candidate["location"] == {"message_index": 0, "action_index": 1}
    assert candidate["output_association"] == "assistant_turn_window"
    assert [item["text"] for item in candidate["following_tool_messages"]] == [
        "first output",
        "second output",
    ]


def test_event_results_link_by_run_id_and_preserve_truncated_output_hash(scanner, tmp_path):
    path = tmp_path / "events.jsonl"
    large_output = "value" * 4000
    events = [
        {"event": "model_request", "data": {"text": "cat /tests/test_outputs.py"}},
        {
            "event": "tool_start",
            "data": {
                "run_id": "selected",
                "name": "verify_candidate",
                "input": {"command": "cat /logs/verifier/*"},
            },
        },
        {"event": "tool_result", "data": {"run_id": "unrelated", "output": "wrong result"}},
        {"event": "tool_result", "data": {"run_id": "selected", "output": large_output}},
    ]
    path.write_text("\n".join(json.dumps(event, separators=(",", ":")) for event in events) + "\n")
    trace_sha, observed, candidates = scanner.scan_events(path)
    assert trace_sha == scanner.digest(path) and observed == 1
    result = candidates[0]["result"]
    assert candidates[0]["role"] == "grader" and result["line"] == 4
    assert result["truncated"] and result["chars"] == len(large_output)
    assert result == {"line": 4, "event": "tool_result", **scanner.output_record(large_output)}


def test_resume_reuses_unchanged_trace_and_rescans_changed_trace(scanner, tmp_path, monkeypatch):
    trial = row(tmp_path)
    trace = native(Path(trial["trial"]) / "agent/mini-trajectory.json", "echo ordinary")
    report = write_json(tmp_path / "report.json", {"trials": [trial, row(tmp_path, reward=None)]})
    first = scanner.scan_report(report, scanner.digest(report))
    previous = write_json(tmp_path / "previous.json", first)
    scan_native = scanner.scan_native
    with monkeypatch.context() as context:
        context.setattr(
            scanner, "scan_native", lambda *_: pytest.fail("unchanged trace was parsed")
        )
        resumed = scanner.scan_report(
            report, scanner.digest(report), previous, scanner.digest(previous)
        )
    assert resumed["summary"]["reused_traces"] == resumed["summary"]["scored_trials"] == 1
    assert resumed["trials"][0]["trace_sha256"] == first["trials"][0]["trace_sha256"]
    native(trace, "cat /solution/solve.sh")
    changed = scanner.scan_report(
        report, scanner.digest(report), previous, scanner.digest(previous)
    )
    assert scanner.scan_native is scan_native
    assert changed["summary"]["reused_traces"] == 0
    assert changed["summary"]["candidate_tools"] == 1
    assert changed["trials"][0]["previous_trace_sha256"] == first["trials"][0]["trace_sha256"]


def test_missing_trace_stays_visible_and_duplicate_scored_cells_are_rejected(scanner, tmp_path):
    trial = row(tmp_path)
    report = write_json(tmp_path / "report.json", {"trials": [trial]})
    result = scanner.scan_report(report, scanner.digest(report))
    assert result["summary"]["missing_traces"] == 1 and result["summary"]["checked_trials"] == 0
    write_json(report, {"trials": [trial, {**trial, "trial": "another-trial"}]})
    with pytest.raises(ValueError, match="duplicate scored"):
        scanner.scan_report(report, scanner.digest(report))


def test_changed_report_or_resume_hash_and_rules_are_rejected(scanner, tmp_path):
    report = write_json(tmp_path / "report.json", {"trials": []})
    with pytest.raises(ValueError, match="report hash"):
        scanner.scan_report(report, "wrong")
    previous = write_json(
        tmp_path / "previous.json", scanner.scan_report(report, scanner.digest(report))
    )
    with pytest.raises(ValueError, match="Previous scan hash"):
        scanner.scan_report(report, scanner.digest(report), previous, "wrong")
    changed = json.loads(previous.read_text())
    changed["patterns"]["extra"] = "different"
    write_json(previous, changed)
    with pytest.raises(ValueError, match="different candidate rules"):
        scanner.scan_report(report, scanner.digest(report), previous, scanner.digest(previous))
