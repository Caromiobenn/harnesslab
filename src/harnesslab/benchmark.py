"""Benchmark v0.2 public/private schemas and catalog loading."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, model_validator

from harnesslab.models import AgentTaskView, StrictModel, TaskCategory

BENCHMARK_SCHEMA_VERSION = "0.2"


class TaskEnvironment(StrictModel):
    toolset: str | None = None
    workspace: Literal["none", "fresh"] = "none"
    fixture: Path | None = None
    writable_paths: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def fixture_requires_workspace(self) -> TaskEnvironment:
        if self.fixture is not None and self.workspace != "fresh":
            raise ValueError("workspace fixtures require workspace='fresh'")
        for raw_path in self.writable_paths:
            path = Path(raw_path)
            if not raw_path.startswith("/") or ".." in path.parts:
                raise ValueError(f"writable path must be an absolute virtual path: {raw_path!r}")
        return self


class OutputContract(StrictModel):
    mode: Literal["json", "text", "files", "patch"]
    schema_name: str | None = None
    json_schema: dict[str, Any] | None = None

    @model_validator(mode="after")
    def json_mode_requires_schema(self) -> OutputContract:
        if self.mode == "json" and self.json_schema is None:
            raise ValueError("json output contracts require an inline json_schema")
        return self


class ExecutionLimits(StrictModel):
    actor_model_calls: int = Field(default=12, ge=1, le=100)
    domain_tool_calls: int = Field(default=30, ge=0, le=500)
    wall_clock_seconds: int = Field(default=180, ge=1, le=3600)


class PublicTaskSpec(StrictModel):
    """Versioned task data that may be shown to an evaluated Agent."""

    schema_version: Literal["0.2"] = BENCHMARK_SCHEMA_VERSION
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]+$")
    revision: int = Field(ge=1)
    category: TaskCategory
    instruction: str = Field(min_length=1)
    input: dict[str, Any] = Field(default_factory=dict)
    environment: TaskEnvironment = Field(default_factory=TaskEnvironment)
    output_contract: OutputContract
    limits: ExecutionLimits = Field(default_factory=ExecutionLimits)
    tags: list[str] = Field(default_factory=list)

    @property
    def task_ref(self) -> str:
        return f"{self.id}@{self.revision}"

    def agent_view(self) -> AgentTaskView:
        return AgentTaskView(
            id=self.id,
            category=self.category,
            instruction=self.instruction,
            input=self.input,
            toolset=self.environment.toolset,
            workspace=self.environment.workspace,
            writable_paths=self.environment.writable_paths,
            output_contract=self.output_contract.model_dump(mode="json"),
            limits=self.limits.model_dump(mode="json"),
            tags=self.tags,
        )


class PrivateValidatorSpec(StrictModel):
    kind: Literal[
        "json_schema",
        "canonical_json",
        "contacts_normalization",
        "invoice_reconciliation",
        "workspace_integrity",
        "sales_rollup",
    ]
    hard: bool = True
    weight: float = Field(default=1.0, gt=0.0)
    parameters: dict[str, Any] = Field(default_factory=dict)


class FaultRule(StrictModel):
    fault_id: str = Field(min_length=1)
    tool: str
    occurrence: int = Field(default=1, ge=1)
    effect: dict[str, Any]


class EvaluationSpec(StrictModel):
    """Private oracle data that must never cross the Harness boundary."""

    schema_version: Literal["0.2"] = BENCHMARK_SCHEMA_VERSION
    task_ref: str
    fixture_ref: str | None = None
    reference_submission: Any = None
    validators: list[PrivateValidatorSpec] = Field(min_length=1)
    fault_variants: dict[str, list[FaultRule]] = Field(default_factory=dict)


class CatalogCaseReference(StrictModel):
    public: Path
    evaluation: Path


class BenchmarkCatalogSpec(StrictModel):
    schema_version: Literal["0.2"] = BENCHMARK_SCHEMA_VERSION
    name: str
    cases: list[CatalogCaseReference] = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    public_path: Path
    evaluation_path: Path
    public: PublicTaskSpec
    evaluation: EvaluationSpec
    workspace_fixture_path: Path | None = None
    workspace_fixture: WorkspaceFixture | None = None


class WorkspaceFixture(StrictModel):
    """Public files materialized into a fresh per-run workspace."""

    schema_version: Literal["0.2"] = BENCHMARK_SCHEMA_VERSION
    directories: list[str] = Field(default_factory=list)
    files: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def paths_are_relative_and_safe(self) -> WorkspaceFixture:
        paths = [*self.directories, *self.files]
        for raw_path in paths:
            path = Path(raw_path)
            if path.is_absolute() or ".." in path.parts or not path.parts:
                raise ValueError(f"workspace fixture path must be safe and relative: {raw_path!r}")
        return self


@dataclass(frozen=True, slots=True)
class LoadedBenchmarkCatalog:
    catalog_path: Path
    spec: BenchmarkCatalogSpec
    cases: tuple[BenchmarkCase, ...]


def _read_yaml(path: Path) -> object:
    if not path.is_file():
        raise FileNotFoundError(f"benchmark YAML file does not exist: {path}")
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def load_benchmark_catalog(path: str | Path) -> LoadedBenchmarkCatalog:
    catalog_path = Path(path).expanduser().resolve()
    spec = BenchmarkCatalogSpec.model_validate(_read_yaml(catalog_path))
    cases: list[BenchmarkCase] = []
    seen_refs: set[str] = set()

    for reference in spec.cases:
        public_path = (catalog_path.parent / reference.public).resolve()
        evaluation_path = (catalog_path.parent / reference.evaluation).resolve()
        public = PublicTaskSpec.model_validate(_read_yaml(public_path))
        evaluation = EvaluationSpec.model_validate(_read_yaml(evaluation_path))
        if evaluation.task_ref != public.task_ref:
            raise ValueError(
                f"evaluation task_ref {evaluation.task_ref!r} does not match "
                f"public task {public.task_ref!r}"
            )
        if public.task_ref in seen_refs:
            raise ValueError(f"duplicate benchmark task_ref: {public.task_ref}")
        seen_refs.add(public.task_ref)
        workspace_fixture_path = None
        workspace_fixture = None
        if public.environment.fixture is not None:
            workspace_fixture_path = (public_path.parent / public.environment.fixture).resolve()
            workspace_fixture = WorkspaceFixture.model_validate(_read_yaml(workspace_fixture_path))
        cases.append(
            BenchmarkCase(
                public_path=public_path,
                evaluation_path=evaluation_path,
                public=public,
                evaluation=evaluation,
                workspace_fixture_path=workspace_fixture_path,
                workspace_fixture=workspace_fixture,
            )
        )

    return LoadedBenchmarkCatalog(catalog_path=catalog_path, spec=spec, cases=tuple(cases))
