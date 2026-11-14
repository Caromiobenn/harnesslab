"""Paired summaries preserve task coverage, missing metrics and failed-attempt costs."""

import importlib
import json
from pathlib import Path

import pytest


@pytest.fixture
def reporter(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    return importlib.import_module("report_coding_pairs")


def row(name, task="a", group="deepagents_default", network="offline", reward=1, **fields):
    return {
        "outcome_path": name,
        "trial": "/trials/" + name,
        "task": task,
        "group": group,
        "network": network,
        "repeat": 0,
        "reward": reward,
        "score_source": "original_verifier",
        "pipeline_ok": True,
        "usage_completeness": "complete",
        "response_transport": "streaming",
        "request_adapter": "native_tool_images_v1",
        **fields,
    }


def source(rows, repeats=1):
    return {
        "configuration": {
            "groups": ["deepagents_default", "rubric_evidence"],
            "tasks": ["a", "b"],
            "repeats": repeats,
        },
        "trials": rows,
    }


def test_matching_retains_failed_cost_and_missing_usage(reporter, tmp_path):
    data = source(
        [
            row("failed", reward=None, output_tokens=7, usage_completeness="partial"),
            row("base", reward=0, output_tokens=10),
            row("treatment", group="rubric_evidence", output_tokens=40, input_tokens=100),
            row("unpaired", task="b", output_tokens=2000),
        ]
    )
    report = reporter.paired_report(data)
    assert len(report["pairs"]) == 1
    pair = report["pairs"][0]
    assert pair["baseline_attempts"] == 2 and pair["baseline_partial_usage_attempts"] == 1
    assert pair["metrics"]["output_tokens"]["observed_delta"] == 23
    assert pair["metrics"]["input_tokens"]["observed_delta"] is None
    summary = report["comparisons"][0]
    assert summary["paired_cells"] == summary["improvements"] == 1
    assert summary["metrics"]["output_tokens"]["baseline"]["sum"] == 17
    assert summary["metrics"]["input_tokens"]["paired_cells_with_values"] == 0
    assert summary["metrics"]["input_tokens"]["baseline_missing_attempts"] == 2
    assert report["coverage"][0]["expected_pairs"] == 2
    assert report["coverage"][0]["scored_pairs"] == 1
    reporter.write_pairs(report, tmp_path)
    assert json.loads((tmp_path / "pairs.json").read_text())["pairs"] == report["pairs"]
    assert {path.name for path in tmp_path.iterdir()} == {
        "pairs.json",
        "pairs.csv",
        "comparisons.csv",
        "costs.csv",
        "coverage.csv",
    }


def test_runtime_cohorts_and_zero_values_stay_distinct(reporter):
    data = source(
        [
            row("a-base", reward=1, output_tokens=0),
            row("a-treated", group="rubric_evidence", reward=0, output_tokens=3),
            row("b-base", task="b", response_transport="non_streaming", output_tokens=8),
            row(
                "b-treated",
                task="b",
                group="rubric_evidence",
                response_transport="non_streaming",
                output_tokens=5,
            ),
        ]
    )
    report = reporter.paired_report(data)
    assert len(report["comparisons"]) == 2
    assert sum(r["regressions"] for r in report["comparisons"]) == 1
    assert sum(r["both_pass"] for r in report["comparisons"]) == 1
    assert sorted(r["metrics"]["output_tokens"]["delta"]["sum"] for r in report["comparisons"]) == [
        -3,
        3,
    ]


def test_network_pair_requires_same_repeat(reporter):
    data = source(
        [
            row("offline", reward=0, output_tokens=5),
            row("public-unmatched", network="public", repeat=1, output_tokens=10),
            row("public-matched", network="public", output_tokens=9),
        ],
        repeats=2,
    )
    report = reporter.paired_report(data)
    assert len(report["pairs"]) == 1
    pair = report["pairs"][0]
    assert pair["kind"] == "network" and pair["reward_delta"] == 1
    assert pair["metrics"]["output_tokens"]["observed_delta"] == 4


def test_python_runtime_change_keeps_paired_cohorts_separate(reporter):
    rows = []
    for task, enabled in [("a", False), ("b", True)]:
        for group in ("deepagents_default", "rubric_evidence"):
            rows.append(row(task + group, task=task, group=group, actor_python_fallback=enabled))
    report = reporter.paired_report(source(rows))
    assert len(report["comparisons"]) == 2
    assert {c["baseline_runtime"]["actor_python_fallback"] for c in report["comparisons"]} == {
        False,
        True,
    }


@pytest.mark.parametrize("duplicate_path", [False, True])
def test_duplicate_scores_or_cost_sources_are_rejected(reporter, duplicate_path):
    data = source([row("one"), row("one" if duplicate_path else "two")])
    with pytest.raises(ValueError, match=r"Duplicate outcome|Multiple official scores"):
        reporter.paired_report(data)


def test_cli_rejects_changed_snapshot(reporter, tmp_path, monkeypatch):
    path = tmp_path / "report.json"
    path.write_text(json.dumps(source([])))
    monkeypatch.setattr(
        "sys.argv",
        [
            "pairs",
            "--report",
            str(path),
            "--report-sha256",
            "incorrect",
            "--output",
            str(tmp_path / "output"),
        ],
    )
    with pytest.raises(ValueError, match="Source report hash changed"):
        reporter.main()
    assert not (tmp_path / "output").exists()
