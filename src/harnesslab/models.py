"""Versioned data contracts for tasks, traces, evaluations, and experiment runs."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "0.1"


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class StrictModel(BaseModel):
    """Base class that rejects misspelled or unsupported configuration fields."""

    model_config = ConfigDict(extra="forbid")


class TaskCategory(StrEnum):
    FILE = "file"
    CODE = "code"
    STRUCTURED_OUTPUT = "structured_output"
    TOOL_USE = "tool_use"
    LONG_HORIZON = "long_horizon"
    TRAVEL = "travel"


class RunStatus(StrEnum):
    COMPLETED = "completed"
    ERROR = "error"


class HarnessKind(StrEnum):
    MOCK = "mock"
    LANGCHAIN_BASELINE = "langchain_baseline"
    LANGCHAIN_PLANNING = "langchain_planning"
    DEEPAGENTS_DEFAULT = "deepagents_default"


class TraceEventKind(StrEnum):
    HARNESS_CONFIGURED = "harness_configured"
    RUN_STARTED = "run_started"
    TOOL_CALLED = "tool_called"
    TOOL_RETURNED = "tool_returned"
    TOOL_ERRORED = "tool_errored"
    MODEL_CALLED = "model_called"
    MODEL_RETURNED = "model_returned"
    MODEL_ERRORED = "model_errored"
    CANDIDATE_COMPLETED = "candidate_completed"
    RUBRIC_EVALUATED = "rubric_evaluated"
    VALIDATION_COMPLETED = "validation_completed"
    RUN_COMPLETED = "run_completed"
    RUN_ERRORED = "run_errored"


class OfflineFixture(StrictModel):
    """Deterministic execution fixture used only by the API-free mock harness."""

    tool: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)


class ValidatorSpec(StrictModel):
    kind: Literal["exact_match"]


class AgentTaskView(StrictModel):
    """Public task data that an evaluated agent is allowed to observe."""

    id: str
    category: TaskCategory
    instruction: str
    input: dict[str, Any] = Field(default_factory=dict)
    toolset: str | None = None
    workspace: str | None = None
    writable_paths: list[str] = Field(default_factory=list)
    output_contract: dict[str, Any] = Field(default_factory=dict)
    limits: dict[str, int] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)

    def render_user_prompt(self) -> str:
        """Render only public task fields into a provider-neutral prompt."""
        import json

        serialized_input = json.dumps(self.input, ensure_ascii=False, sort_keys=True)
        serialized_contract = json.dumps(
            self.output_contract,
            ensure_ascii=False,
            sort_keys=True,
        )
        sections = [self.instruction, f"Task input (JSON):\n{serialized_input}"]
        if self.toolset is not None:
            sections.append(f"Available domain toolset: {self.toolset}")
        if self.workspace == "fresh":
            writable = json.dumps(self.writable_paths, ensure_ascii=False)
            sections.append(
                "A fresh isolated virtual workspace is available. "
                f"Writable paths (JSON): {writable}"
            )
        if self.output_contract:
            sections.append(f"Required output contract (JSON):\n{serialized_contract}")
        return "\n\n".join(sections)


class TaskDefinition(StrictModel):
    schema_version: Literal["0.1"] = SCHEMA_VERSION
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]+$")
    category: TaskCategory
    instruction: str = Field(min_length=1)
    input: dict[str, Any] = Field(default_factory=dict)
    offline_fixture: OfflineFixture | None = None
    expected: Any
    validators: list[ValidatorSpec] = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def fixture_arguments_match_input(self) -> TaskDefinition:
        """Keep smoke fixtures explicit and prevent accidental hidden test inputs."""
        if self.offline_fixture is not None and self.offline_fixture.arguments != self.input:
            msg = "offline_fixture.arguments must equal task input in schema version 0.1"
            raise ValueError(msg)
        return self

    def agent_view(self) -> AgentTaskView:
        """Construct the answer-free view passed across the harness boundary."""
        return AgentTaskView(
            id=self.id,
            category=self.category,
            instruction=self.instruction,
            input=self.input,
            tags=self.tags,
        )


class ValidationCheck(StrictModel):
    validator: str
    passed: bool
    score: float = Field(ge=0.0, le=1.0)
    message: str
    evidence: dict[str, Any] = Field(default_factory=dict)


class EvaluationResult(StrictModel):
    passed: bool
    score: float = Field(ge=0.0, le=1.0)
    checks: list[ValidationCheck]


class UsageMetrics(StrictModel):
    model_calls: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    estimated_cost_usd: float = Field(default=0.0, ge=0.0)
    duration_ms: float = Field(default=0.0, ge=0.0)


class TraceEvent(StrictModel):
    schema_version: Literal["0.1"] = SCHEMA_VERSION
    run_id: str
    sequence: int = Field(ge=0)
    timestamp: datetime = Field(default_factory=utc_now)
    kind: TraceEventKind
    name: str
    payload: dict[str, Any] = Field(default_factory=dict)
    duration_ms: float | None = Field(default=None, ge=0.0)


class RunRecord(StrictModel):
    schema_version: Literal["0.1"] = SCHEMA_VERSION
    run_id: str
    experiment: str
    task_id: str
    harness: str
    model: str
    repeat: int = Field(ge=0)
    seed: int
    status: RunStatus
    success: bool
    started_at: datetime
    ended_at: datetime
    output: Any = None
    evaluation: EvaluationResult | None = None
    metrics: UsageMetrics
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class ExperimentSummary(StrictModel):
    schema_version: Literal["0.1"] = SCHEMA_VERSION
    experiment: str
    harness: str
    model: str
    total_runs: int = Field(ge=0)
    successful_runs: int = Field(ge=0)
    validation_failures: int = Field(ge=0)
    execution_errors: int = Field(ge=0)
    success_rate: float = Field(ge=0.0, le=1.0)
    started_at: datetime
    ended_at: datetime
    duration_ms: float = Field(ge=0.0)
    artifact_directory: str
