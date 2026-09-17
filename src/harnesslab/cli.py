"""Command-line interface for running reproducible HarnessLab experiments."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from tempfile import TemporaryDirectory

from harnesslab.benchmark import BenchmarkCase, load_benchmark_catalog
from harnesslab.benchmark_runner import run_benchmark_experiment
from harnesslab.config import load_benchmark_experiment, load_experiment
from harnesslab.reporting import load_run_records, summarize_run_records, write_summary
from harnesslab.runner import run_experiment
from harnesslab.validators import evaluate_benchmark_submission
from harnesslab.workspace import apply_reference_files, materialize_workspace


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="harnesslab", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="run an experiment YAML file")
    run_parser.add_argument("config", type=Path, help="path to an experiment YAML file")
    run_parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="override the configured artifact root directory",
    )
    run_parser.add_argument(
        "--fail-on-validation",
        action="store_true",
        help="return exit code 1 when any deterministic validator fails",
    )
    benchmark_parser = subparsers.add_parser(
        "run-benchmark",
        help="run a Benchmark v0.2 experiment against an OpenAI-compatible model",
    )
    benchmark_parser.add_argument("config", type=Path, help="path to a v0.2 experiment YAML")
    benchmark_parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="override the configured artifact root directory",
    )
    benchmark_parser.add_argument(
        "--fail-on-validation",
        action="store_true",
        help="return exit code 1 when any deterministic validator fails",
    )
    verify_parser = subparsers.add_parser(
        "verify-benchmark",
        help="validate private references against a benchmark catalog",
    )
    verify_parser.add_argument("catalog", type=Path, help="path to catalog YAML")
    summarize_parser = subparsers.add_parser(
        "summarize-benchmark",
        help="rebuild comparison metrics from one or more benchmark artifact trees",
    )
    summarize_parser.add_argument("artifacts", type=Path, nargs="+")
    summarize_parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="create the same JSON summary at this path",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "run":
        loaded = load_experiment(args.config)
        result = run_experiment(loaded, output_root=args.output_dir)
        print(json.dumps(result.summary.model_dump(mode="json"), ensure_ascii=False, indent=2))
        failed = result.summary.execution_errors > 0 or (
            args.fail_on_validation and result.summary.validation_failures > 0
        )
        return 1 if failed else 0
    if args.command == "run-benchmark":
        loaded = load_benchmark_experiment(args.config)
        result = run_benchmark_experiment(loaded, output_root=args.output_dir)
        print(json.dumps(result.summary.model_dump(mode="json"), ensure_ascii=False, indent=2))
        failed = result.summary.execution_errors > 0 or (
            args.fail_on_validation and result.summary.validation_failures > 0
        )
        return 1 if failed else 0
    if args.command == "verify-benchmark":
        catalog = load_benchmark_catalog(args.catalog)
        cases = []
        for case in catalog.cases:
            evaluation = _evaluate_reference(case)
            cases.append(
                {
                    "task_ref": case.public.task_ref,
                    "passed": evaluation.passed,
                    "score": evaluation.score,
                    "checks": [
                        {"validator": check.validator, "passed": check.passed}
                        for check in evaluation.checks
                    ],
                }
            )
        passed = all(case["passed"] for case in cases)
        print(
            json.dumps(
                {
                    "schema_version": catalog.spec.schema_version,
                    "catalog": catalog.spec.name,
                    "total_cases": len(cases),
                    "passed_cases": sum(case["passed"] for case in cases),
                    "passed": passed,
                    "cases": cases,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if passed else 1
    if args.command == "summarize-benchmark":
        summary = summarize_run_records(load_run_records(args.artifacts))
        if args.output is not None:
            write_summary(args.output, summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    return 2


def _evaluate_reference(case: BenchmarkCase):
    if case.public.environment.workspace == "none":
        return evaluate_benchmark_submission(case, case.evaluation.reference_submission)
    with TemporaryDirectory(prefix="harnesslab-reference-") as temporary_directory:
        workspace = materialize_workspace(case, Path(temporary_directory) / "workspace")
        if workspace is None:
            raise AssertionError("fresh workspace case did not materialize a workspace")
        apply_reference_files(workspace, case.evaluation.reference_submission)
        return evaluate_benchmark_submission(
            case,
            case.evaluation.reference_submission,
            workspace=workspace,
        )
