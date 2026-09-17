from pathlib import Path

from harnesslab.benchmark import load_benchmark_catalog
from harnesslab.validators import evaluate_benchmark_submission
from harnesslab.workspace import apply_reference_files, materialize_workspace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CATALOG = PROJECT_ROOT / "benchmarks/catalog-v0.2.yaml"


def test_catalog_loads_public_and_private_files_separately() -> None:
    catalog = load_benchmark_catalog(CATALOG)

    assert len(catalog.cases) == 3
    assert {case.public.task_ref for case in catalog.cases} == {
        "structured.contacts-normalize.v1@1",
        "structured.invoice-reconcile.v1@1",
        "file.sales-rollup.v1@1",
    }
    for case in catalog.cases:
        public_fields = type(case.public).model_fields
        assert "reference_submission" not in public_fields
        assert "validators" not in public_fields
        prompt = case.public.agent_view().render_user_prompt()
        assert "reference_submission" not in prompt
        assert "validators" not in prompt


def test_all_reference_submissions_pass_independent_validators(tmp_path: Path) -> None:
    catalog = load_benchmark_catalog(CATALOG)

    for index, case in enumerate(catalog.cases):
        workspace = materialize_workspace(case, tmp_path / f"workspace-{index}")
        if workspace is not None:
            apply_reference_files(workspace, case.evaluation.reference_submission)
        result = evaluate_benchmark_submission(
            case,
            case.evaluation.reference_submission,
            workspace=workspace,
        )
        assert result.passed is True, case.public.task_ref
        assert all(check.passed for check in result.checks)


def test_contacts_validator_rejects_missing_merged_tags() -> None:
    case = load_benchmark_catalog(CATALOG).cases[0]
    invalid = {
        "contacts": [
            {
                "email": "alice@example.com",
                "name": "Alice Chen",
                "phone": "8613800138000",
                "tags": ["vip"],
            }
        ]
    }

    result = evaluate_benchmark_submission(case, invalid)

    assert result.passed is False
    checks = {check.validator: check for check in result.checks}
    assert checks["contacts_normalization"].passed is False


def test_invoice_validator_rejects_rounding_at_the_wrong_stage() -> None:
    case = load_benchmark_catalog(CATALOG).cases[1]
    invalid = dict(case.evaluation.reference_submission)
    invalid["subtotal"] = "52.64"

    result = evaluate_benchmark_submission(case, invalid)

    assert result.passed is False
    checks = {check.validator: check for check in result.checks}
    assert checks["invoice_reconciliation"].passed is False


def test_file_validator_rejects_wrong_rollup_and_modified_input(tmp_path: Path) -> None:
    case = load_benchmark_catalog(CATALOG).cases[2]
    workspace = materialize_workspace(case, tmp_path / "workspace")
    assert workspace is not None
    apply_reference_files(
        workspace,
        {
            "files": {
                "output/summary.json": '{"regions": [], "grand_total": "0.00"}',
            }
        },
    )
    input_path = workspace / "input/batch-a.json"
    input_path.chmod(0o644)
    input_path.write_text("{}", encoding="utf-8")

    result = evaluate_benchmark_submission(case, None, workspace=workspace)

    assert result.passed is False
    checks = {check.validator: check for check in result.checks}
    assert checks["workspace_integrity"].passed is False
    assert checks["sales_rollup"].passed is False
