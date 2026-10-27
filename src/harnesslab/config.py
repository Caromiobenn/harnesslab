"""Load strict YAML experiment files and their referenced task definitions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, model_validator

from harnesslab.benchmark import BenchmarkCase, LoadedBenchmarkCatalog, load_benchmark_catalog
from harnesslab.models import (
    SCHEMA_VERSION,
    HarnessKind,
    StrictModel,
    TaskDefinition,
)


class ExperimentSettings(StrictModel):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]+$")
    description: str = ""
    repeats: int = Field(default=1, ge=1, le=100)
    seed: int = 0


class HarnessSettings(StrictModel):
    kind: HarnessKind
    model: str = Field(min_length=1)


class OpenAICompatibleModelSettings(StrictModel):
    """Secret-free settings for an OpenAI-compatible chat-completions endpoint."""

    provider: Literal["openai_compatible"] = "openai_compatible"
    name: str = Field(min_length=1)
    base_url: str = Field(min_length=1)
    api_key_env: str | None = Field(default="OPENAI_API_KEY", min_length=1)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_completion_tokens: int = Field(default=2048, ge=1, le=131_072)
    request_timeout_seconds: float = Field(default=120.0, gt=0.0, le=3600.0)
    max_retries: int = Field(default=1, ge=0, le=10)
    extra_body: dict[str, Any] = Field(default_factory=dict)
    input_cost_per_million_usd: float | None = Field(default=None, ge=0.0)
    output_cost_per_million_usd: float | None = Field(default=None, ge=0.0)

    @model_validator(mode="after")
    def pricing_is_all_or_nothing(self) -> OpenAICompatibleModelSettings:
        prices = (self.input_cost_per_million_usd, self.output_cost_per_million_usd)
        if (prices[0] is None) != (prices[1] is None):
            raise ValueError("input and output token prices must be configured together")
        return self


class VerificationSettings(StrictModel):
    """Explicit runtime treatments; private validators are never available here."""

    mode: Literal["none", "retry", "rubric"] = "none"
    evidence_tools: bool = False
    max_iterations: int = Field(default=3, ge=1, le=5)
    total_model_call_limit: int = Field(default=24, ge=1, le=200)
    total_tool_call_limit: int = Field(default=60, ge=1, le=500)
    grader_call_limit: int = Field(default=12, ge=1, le=100)
    grader_model: OpenAICompatibleModelSettings | None = None

    @model_validator(mode="after")
    def evidence_requires_rubric(self) -> VerificationSettings:
        if self.evidence_tools and self.mode != "rubric":
            raise ValueError("evidence_tools requires mode='rubric'")
        return self


class BenchmarkHarnessSettings(StrictModel):
    kind: HarnessKind
    model: OpenAICompatibleModelSettings
    verification: VerificationSettings = Field(default_factory=VerificationSettings)

    @model_validator(mode="after")
    def real_framework_harness_required(self) -> BenchmarkHarnessSettings:
        if self.kind is HarnessKind.MOCK:
            raise ValueError("Benchmark v0.2 requires a real framework harness")
        if self.verification.mode != "none" and self.kind is not HarnessKind.DEEPAGENTS_DEFAULT:
            raise ValueError("runtime verification currently requires deepagents_default")
        return self


class OutputSettings(StrictModel):
    directory: Path


class ExperimentConfig(StrictModel):
    schema_version: Literal["0.1"] = SCHEMA_VERSION
    experiment: ExperimentSettings
    harness: HarnessSettings
    tasks: list[Path] = Field(min_length=1)
    output: OutputSettings


class BenchmarkExperimentConfig(StrictModel):
    schema_version: Literal["0.2"]
    experiment: ExperimentSettings
    harness: BenchmarkHarnessSettings
    catalog: Path
    task_refs: list[str] | None = Field(default=None, min_length=1)
    output: OutputSettings


@dataclass(frozen=True, slots=True)
class LoadedExperiment:
    config_path: Path
    config: ExperimentConfig
    tasks: tuple[TaskDefinition, ...]
    output_directory: Path


@dataclass(frozen=True, slots=True)
class LoadedBenchmarkExperiment:
    config_path: Path
    config: BenchmarkExperimentConfig
    catalog: LoadedBenchmarkCatalog
    cases: tuple[BenchmarkCase, ...]
    output_directory: Path


def _read_yaml(path: Path) -> object:
    if not path.is_file():
        raise FileNotFoundError(f"YAML file does not exist: {path}")
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def load_experiment(path: str | Path) -> LoadedExperiment:
    """Load an experiment, resolving task and output paths from the config directory."""
    config_path = Path(path).expanduser().resolve()
    raw_config = _read_yaml(config_path)
    config = ExperimentConfig.model_validate(raw_config)

    tasks: list[TaskDefinition] = []
    seen_ids: set[str] = set()
    for relative_task_path in config.tasks:
        task_path = (config_path.parent / relative_task_path).resolve()
        task = TaskDefinition.model_validate(_read_yaml(task_path))
        if task.id in seen_ids:
            raise ValueError(f"duplicate task id in experiment: {task.id}")
        seen_ids.add(task.id)
        tasks.append(task)

    output_directory = (config_path.parent / config.output.directory).resolve()
    return LoadedExperiment(
        config_path=config_path,
        config=config,
        tasks=tuple(tasks),
        output_directory=output_directory,
    )


def load_benchmark_experiment(path: str | Path) -> LoadedBenchmarkExperiment:
    """Load a v0.2 benchmark experiment and resolve its catalog and task selection."""
    config_path = Path(path).expanduser().resolve()
    config = BenchmarkExperimentConfig.model_validate(_read_yaml(config_path))
    catalog_path = (config_path.parent / config.catalog).resolve()
    catalog = load_benchmark_catalog(catalog_path)

    cases = catalog.cases
    if config.task_refs is not None:
        selected = set(config.task_refs)
        available = {case.public.task_ref for case in catalog.cases}
        unknown = selected - available
        if unknown:
            raise ValueError(f"unknown benchmark task_ref(s): {', '.join(sorted(unknown))}")
        cases = tuple(case for case in catalog.cases if case.public.task_ref in selected)

    output_directory = (config_path.parent / config.output.directory).resolve()
    return LoadedBenchmarkExperiment(
        config_path=config_path,
        config=config,
        catalog=catalog,
        cases=cases,
        output_directory=output_directory,
    )
