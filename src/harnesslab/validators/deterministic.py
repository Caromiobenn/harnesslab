"""Validators whose evidence can be reproduced without an LLM judge."""

from __future__ import annotations

from typing import Any

from harnesslab.models import EvaluationResult, TaskDefinition, ValidationCheck


def _exact_match(output: Any, expected: Any) -> ValidationCheck:
    passed = output == expected
    message = "output exactly matches expected value" if passed else "output differs from expected"
    return ValidationCheck(
        validator="exact_match",
        passed=passed,
        score=1.0 if passed else 0.0,
        message=message,
        evidence={"expected": expected, "actual": output},
    )


def evaluate_task(task: TaskDefinition, output: Any) -> EvaluationResult:
    checks: list[ValidationCheck] = []
    for validator in task.validators:
        if validator.kind == "exact_match":
            checks.append(_exact_match(output, task.expected))

    passed = all(check.passed for check in checks)
    score = sum(check.score for check in checks) / len(checks)
    return EvaluationResult(passed=passed, score=score, checks=checks)
