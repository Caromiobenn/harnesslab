"""In-memory event collection before atomic run-level JSONL persistence."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from harnesslab.models import TraceEvent, TraceEventKind


class TraceRecorder:
    def __init__(
        self,
        run_id: str,
        *,
        sink: Callable[[TraceEvent], None] | None = None,
    ) -> None:
        self.run_id = run_id
        self.events: list[TraceEvent] = []
        self._sink = sink

    def emit(
        self,
        kind: TraceEventKind,
        name: str,
        *,
        payload: dict[str, Any] | None = None,
        duration_ms: float | None = None,
    ) -> TraceEvent:
        event = TraceEvent(
            run_id=self.run_id,
            sequence=len(self.events),
            kind=kind,
            name=name,
            payload=payload or {},
            duration_ms=duration_ms,
        )
        self.events.append(event)
        if self._sink is not None:
            self._sink(event)
        return event
