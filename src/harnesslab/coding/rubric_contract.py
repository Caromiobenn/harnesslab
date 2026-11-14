"""Align the native rubric grader's output schema with the evidence gate's fixed IDs."""

from __future__ import annotations

from typing import Literal, NotRequired

from deepagents.middleware.rubric import (
    RUBRIC_GRADER_MESSAGE_SOURCE,
    GraderResponse,
    RubricMiddleware,
)
from pydantic import Field, create_model, model_validator
from typing_extensions import TypedDict


def response_schema(names: tuple[str, ...]):
    criterion = TypedDict(  # noqa: UP013 -- criterion names are runtime schema values.
        "CriterionWithId",
        {"name": Literal[tuple(names)], "passed": bool, "gap": NotRequired[str]},
    )

    def check_criteria(self):
        if self.result == "failed" and not self.criteria:
            return self
        actual = [item["name"] for item in self.criteria]
        if len(actual) != len(names) or set(actual) != set(names):
            raise ValueError("Return each required criterion ID exactly once: " + ", ".join(names))
        if any(not item["passed"] and not item.get("gap", "").strip() for item in self.criteria):
            raise ValueError("A failed criterion requires an actionable gap")
        return self

    # Preserve the native tool name and result validation; only the criterion contract changes.
    return create_model(
        "GraderResponse",
        __base__=GraderResponse,
        __validators__={"check_criteria": model_validator(mode="after")(check_criteria)},
        criteria=(
            list[criterion],
            Field(description="One entry per fixed criterion ID, exactly once; do not rename IDs."),
        ),
    )


class FixedCriteriaRubric(RubricMiddleware):
    """Keep native grading/repair and tracing, with an explicit caller-owned criterion set.

    The pinned 0.7.14 factory fixes its response schema internally. This small factory
    override preserves its model, tools, middleware, state/context and native tool name.
    """

    def __init__(self, *, criterion_names: tuple[str, ...], **kwargs):
        super().__init__(**kwargs)
        self.criterion_names = criterion_names
        self.response_schema = response_schema(criterion_names)

    def _ensure_grader(self):
        if self._grader is not None:
            return self._grader
        from deepagents._models import resolve_model
        from langchain.agents import create_agent

        self._resolved_model = resolve_model(self._model)
        self._grader = create_agent(
            model=self._resolved_model,
            system_prompt=self._system_prompt,
            tools=self._tools,
            middleware=self._grader_middleware,
            name=RUBRIC_GRADER_MESSAGE_SOURCE,
            response_format=self.response_schema,
            state_schema=self._grader_state_schema,
            context_schema=self._grader_context_schema,
        )
        return self._grader

    def _build_grader_payload(self, state, iteration, correction=None):
        # Seed the native criteria block from the first pass, retaining its nonce delimiters.
        return super()._build_grader_payload(
            {**state, "_rubric_criteria": list(self.criterion_names)}, iteration, correction
        )
