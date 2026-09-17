"""Independent deterministic validators for Benchmark v0.2 cases."""

from __future__ import annotations

import json
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from harnesslab.benchmark import BenchmarkCase, PrivateValidatorSpec
from harnesslab.models import EvaluationResult, ValidationCheck


def evaluate_benchmark_submission(
    case: BenchmarkCase,
    submission: Any,
    *,
    workspace: Path | None = None,
) -> EvaluationResult:
    checks = [
        _evaluate_one(case, spec, submission, workspace=workspace)
        for spec in case.evaluation.validators
    ]
    hard_checks = [
        check for check, spec in zip(checks, case.evaluation.validators, strict=True) if spec.hard
    ]
    passed = all(check.passed for check in hard_checks)
    total_weight = sum(spec.weight for spec in case.evaluation.validators)
    score = (
        sum(
            check.score * spec.weight
            for check, spec in zip(checks, case.evaluation.validators, strict=True)
        )
        / total_weight
    )
    return EvaluationResult(passed=passed, score=score, checks=checks)


def _evaluate_one(
    case: BenchmarkCase,
    spec: PrivateValidatorSpec,
    submission: Any,
    *,
    workspace: Path | None,
) -> ValidationCheck:
    if spec.kind == "json_schema":
        return _json_schema(case, submission)
    if spec.kind == "canonical_json":
        return _canonical_json(case, submission)
    if spec.kind == "contacts_normalization":
        return _contacts_normalization(case, submission)
    if spec.kind == "invoice_reconciliation":
        return _invoice_reconciliation(case, submission)
    if spec.kind == "workspace_integrity":
        return _workspace_integrity(case, workspace)
    if spec.kind == "sales_rollup":
        return _sales_rollup(case, spec, workspace)
    raise ValueError(f"unsupported benchmark validator: {spec.kind}")


def _json_schema(case: BenchmarkCase, submission: Any) -> ValidationCheck:
    schema = case.public.output_contract.json_schema
    if schema is None:
        raise ValueError(f"task {case.public.task_ref} has no public JSON schema")
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(submission),
        key=lambda error: list(error.absolute_path),
    )
    evidence = {
        "errors": [
            {
                "path": list(error.absolute_path),
                "message": error.message,
            }
            for error in errors
        ]
    }
    return ValidationCheck(
        validator="json_schema",
        passed=not errors,
        score=1.0 if not errors else 0.0,
        message="submission matches public JSON schema"
        if not errors
        else f"submission has {len(errors)} JSON schema error(s)",
        evidence=evidence,
    )


def _canonical_json(case: BenchmarkCase, submission: Any) -> ValidationCheck:
    expected = case.evaluation.reference_submission
    passed = submission == expected
    return ValidationCheck(
        validator="canonical_json",
        passed=passed,
        score=1.0 if passed else 0.0,
        message="submission equals the private canonical result"
        if passed
        else "submission differs from the private canonical result",
        evidence={"expected": expected, "actual": submission},
    )


def _contacts_normalization(case: BenchmarkCase, submission: Any) -> ValidationCheck:
    expected = _normalize_contacts(case.public.input.get("contacts"))
    passed = isinstance(submission, dict) and submission.get("contacts") == expected
    return ValidationCheck(
        validator="contacts_normalization",
        passed=passed,
        score=1.0 if passed else 0.0,
        message="contacts were independently normalized and merged"
        if passed
        else "normalized contacts differ from the independent implementation",
        evidence={"expected_contacts": expected},
    )


def _normalize_contacts(raw_contacts: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_contacts, list):
        raise ValueError("contacts input must be a list")
    merged: dict[str, dict[str, Any]] = {}
    for raw in raw_contacts:
        if not isinstance(raw, dict):
            raise ValueError("each contact must be an object")
        email = str(raw.get("email", "")).strip().lower()
        if not email:
            raise ValueError("every contact needs an email")
        name = " ".join(str(raw.get("name", "")).strip().split())
        phone_digits = "".join(
            character for character in str(raw.get("phone", "")) if character.isdigit()
        )
        tags = {str(tag).strip().lower() for tag in raw.get("tags", []) if str(tag).strip()}
        existing = merged.setdefault(
            email,
            {"email": email, "name": name, "phone": phone_digits, "tags": set()},
        )
        if not existing["name"] and name:
            existing["name"] = name
        if not existing["phone"] and phone_digits:
            existing["phone"] = phone_digits
        existing["tags"].update(tags)
    return [
        {
            "email": email,
            "name": item["name"],
            "phone": item["phone"],
            "tags": sorted(item["tags"]),
        }
        for email, item in sorted(merged.items())
    ]


def _invoice_reconciliation(case: BenchmarkCase, submission: Any) -> ValidationCheck:
    expected = _reconcile_invoice(case.public.input)
    passed = submission == expected
    return ValidationCheck(
        validator="invoice_reconciliation",
        passed=passed,
        score=1.0 if passed else 0.0,
        message="invoice totals match independent Decimal arithmetic"
        if passed
        else "invoice totals or status are incorrect",
        evidence={"expected": expected},
    )


def _money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _reconcile_invoice(task_input: dict[str, Any]) -> dict[str, Any]:
    tax_rate = Decimal(str(task_input["tax_rate_percent"])) / Decimal("100")
    normalized_lines: list[dict[str, str]] = []
    subtotal = Decimal("0")
    for line in sorted(task_input["lines"], key=lambda item: item["id"]):
        quantity = Decimal(str(line["quantity"]))
        unit_price = Decimal(str(line["unit_price"]))
        discount = Decimal(str(line.get("discount_percent", 0))) / Decimal("100")
        net = (quantity * unit_price * (Decimal("1") - discount)).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
        subtotal += net
        normalized_lines.append({"id": line["id"], "net": _money(net)})
    tax = (subtotal * tax_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    total = subtotal + tax
    paid = sum((Decimal(str(value)) for value in task_input["payments"]), Decimal("0"))
    balance = total - paid
    status = "paid" if balance <= 0 else ("partial" if paid > 0 else "unpaid")
    return {
        "lines": normalized_lines,
        "subtotal": _money(subtotal),
        "tax": _money(tax),
        "total": _money(total),
        "paid": _money(paid),
        "balance": _money(balance),
        "status": status,
    }


def _workspace_integrity(case: BenchmarkCase, workspace: Path | None) -> ValidationCheck:
    workspace = _require_workspace(workspace)
    fixture = case.workspace_fixture
    if fixture is None:
        raise ValueError(f"task {case.public.task_ref} has no workspace fixture")
    changed: list[str] = []
    missing: list[str] = []
    for relative_path, expected_content in fixture.files.items():
        if not relative_path.startswith("input/"):
            continue
        path = workspace / relative_path
        if not path.is_file():
            missing.append(relative_path)
        elif path.read_text(encoding="utf-8") != expected_content:
            changed.append(relative_path)
    passed = not missing and not changed
    return ValidationCheck(
        validator="workspace_integrity",
        passed=passed,
        score=1.0 if passed else 0.0,
        message="public input files remain unchanged"
        if passed
        else "one or more public input files were changed or removed",
        evidence={"missing": missing, "changed": changed},
    )


def _sales_rollup(
    case: BenchmarkCase,
    spec: PrivateValidatorSpec,
    workspace: Path | None,
) -> ValidationCheck:
    workspace = _require_workspace(workspace)
    output_path = str(spec.parameters.get("output_path", "/output/summary.json"))
    try:
        actual = _load_workspace_json(workspace, output_path)
    except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return ValidationCheck(
            validator="sales_rollup",
            passed=False,
            score=0.0,
            message="sales rollup output is missing or invalid JSON",
            evidence={"error": f"{type(exc).__name__}: {exc}"},
        )

    totals: dict[str, dict[str, Any]] = {}
    seen_ids: set[str] = set()
    fixture = case.workspace_fixture
    if fixture is None:
        raise ValueError(f"task {case.public.task_ref} has no workspace fixture")
    input_files = {
        path: content
        for path, content in fixture.files.items()
        if path.startswith("input/") and path.endswith(".json")
    }
    for relative_path, content in sorted(input_files.items()):
        payload = json.loads(content)
        for order in payload["orders"]:
            order_id = str(order["id"])
            if order_id in seen_ids:
                raise ValueError(f"duplicate order id in fixture {relative_path}: {order_id}")
            seen_ids.add(order_id)
            if order["status"] != "paid":
                continue
            region = str(order["region"])
            bucket = totals.setdefault(region, {"count": 0, "revenue": Decimal("0")})
            bucket["count"] += 1
            bucket["revenue"] += Decimal(str(order["amount"]))
    regions = [
        {
            "region": region,
            "paid_orders": values["count"],
            "revenue": _money(values["revenue"]),
        }
        for region, values in sorted(totals.items())
    ]
    expected = {
        "regions": regions,
        "grand_total": _money(sum((item["revenue"] for item in totals.values()), Decimal("0"))),
    }
    passed = actual == expected
    return ValidationCheck(
        validator="sales_rollup",
        passed=passed,
        score=1.0 if passed else 0.0,
        message="sales rollup matches independently aggregated paid orders"
        if passed
        else "sales rollup totals, counts, or ordering are incorrect",
        evidence={"expected": expected, "actual": actual},
    )


def _require_workspace(workspace: Path | None) -> Path:
    if workspace is None:
        raise ValueError("validator requires a materialized workspace")
    return workspace


def _load_workspace_json(workspace: Path, virtual_path: str) -> Any:
    relative = virtual_path.lstrip("/")
    path = (workspace / relative).resolve()
    if not path.is_relative_to(workspace.resolve()):
        raise ValueError(f"validator path escapes workspace: {virtual_path}")
    return json.loads(path.read_text(encoding="utf-8"))
