"""Synthetic cases for the paired denominator and review policy formulas."""

import json
import tempfile
import unittest
from pathlib import Path

import analyze


def write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


def score(kind):
    return {
        "function_pass": kind != "failed",
        "qualified": kind == "qualified",
        "requirements_status": {
            "qualified": "satisfied",
            "unresolved": "rebuild_mismatch",
            "miss": "non_native_executable",
            "failed": "missing_executable",
        }[kind],
        "artifact_kind": "elf" if kind in {"qualified", "unresolved"} else "script",
    }


class AnalyzeStudy(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name)
        self.plan = []

    def add_cell(self, first, final, gate, usage=True, status="completed"):
        repeat = len(self.plan) + 1
        task, requirement, toolchain = "toy", "c_required", "setup"
        self.plan.append([task, requirement, toolchain, repeat])
        if final is None:
            return
        folder = self.run / f"{task}--{requirement}--{toolchain}--r{repeat}"
        folder.mkdir()
        trial = {
            "task": task,
            "requirement": requirement,
            "toolchain": toolchain,
            "repeat": repeat,
            "status": status,
            "score": score(final),
            "public_gate": gate,
            "metrics": {"model_responses": 5, "usage_reported": 5 if usage else 3},
        }
        write(folder / "result.json", trial)
        events = [
            {
                "label": "final",
                "score": score(final),
                "seconds": 60,
                "tokens": 170,
                "responses": 5,
                "digest": f"digest-{final}",
            }
        ]
        if first is not None:
            events.insert(
                0,
                {
                    "label": "first_candidate",
                    "score": score(first),
                    "seconds": 45,
                    "tokens": 100,
                    "responses": 3,
                    "digest": f"digest-{first}",
                },
            )
        write(folder / "timeline.json", events)
        (folder / "trajectory.jsonl").write_text("{}\n", encoding="utf-8")

    def evaluate(self, calibration=False):
        write(self.run / "design.json", {"cells": self.plan, "review_rounds": 1})
        return analyze.inspect_run(self.run, calibration)

    def test_policy_coverage_costs_and_case_links(self):
        triggered = {"trigger_review": True, "seconds": 1.25}
        skipped = {"trigger_review": False, "seconds": 1.25}
        self.add_cell("failed", "qualified", triggered)
        self.add_cell("miss", "qualified", skipped)
        self.add_cell("qualified", "failed", skipped)
        self.add_cell("qualified", "unresolved", triggered, usage=False)
        self.add_cell("qualified", "qualified", {"error": "unavailable", **triggered})
        self.add_cell(None, "qualified", triggered)
        self.add_cell("qualified", "qualified", skipped, status="pipeline_error")
        self.add_cell(None, None, None)

        report = self.evaluate()
        delivery = report["delivery"]
        self.assertEqual(report["totals"]["valid_final"], 6)
        self.assertEqual(delivery["paired"], 4)
        self.assertEqual(
            delivery["excluded"],
            {
                "invalid_public_gate": 1,
                "no_first_candidate": 1,
                "pipeline_error": 1,
                "pending": 1,
            },
        )
        self.assertEqual(delivery["review_triggered"], 2)
        by_policy = delivery["policies"]
        self.assertEqual([p["qualified"] for p in by_policy.values()], [2, 2, 2])
        self.assertEqual([p["repairs"] for p in by_policy.values()], [0, 2, 1])
        self.assertEqual([p["regressions"] for p in by_policy.values()], [0, 1, 0])
        self.assertEqual([p["qualification_unresolved"] for p in by_policy.values()], [0, 1, 1])
        self.assertEqual([p["tokens_total"] for p in by_policy.values()], [300, 510, 370])
        self.assertEqual([p["tokens_denominator"] for p in by_policy.values()], [3, 3, 3])
        self.assertEqual([p["seconds_median"] for p in by_policy.values()], [45, 60, 53.75])
        categories = delivery["cases_with_traces"]
        self.assertEqual(len(categories["repair_skipped_by_gate"]), 1)
        self.assertEqual(len(categories["regression_avoided_by_gate"]), 1)
        self.assertEqual(len(categories["regression"][0]["trajectory"]["sha256"]), 64)
        self.assertIn("4/8", analyze.report_text(None, report))

    def test_calibration_keeps_valid_results_without_gate(self):
        self.add_cell("qualified", "qualified", None)
        res = self.evaluate(calibration=True)
        self.assertEqual(res["totals"]["qualified"], 1)
        self.assertNotIn("delivery", res)


if __name__ == "__main__":
    unittest.main()
