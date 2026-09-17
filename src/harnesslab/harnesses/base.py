"""Stable boundary between experiment orchestration and agent frameworks."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from harnesslab.models import AgentTaskView, OfflineFixture, UsageMetrics
from harnesslab.tracing import TraceRecorder


@dataclass(frozen=True, slots=True)
class HarnessRequest:
    """Execution input with no validator or expected-answer fields."""

    task: AgentTaskView
    scripted_fixture: OfflineFixture | None = None
    seed: int = 0
    workspace: Path | None = None


@dataclass(frozen=True, slots=True)
class HarnessExecution:
    output: Any
    metrics: UsageMetrics
    diagnostics: dict[str, Any] = field(default_factory=dict)


class AgentHarness(Protocol):
    model_name: str

    def execute(self, request: HarnessRequest, trace: TraceRecorder) -> HarnessExecution:
        """Execute one task and return framework-neutral output and measurements."""
        ...
