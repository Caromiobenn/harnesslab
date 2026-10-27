"""Public-only runtime feedback, candidate snapshots, and read-only evidence.

This module deliberately accepts HarnessRequest, never BenchmarkCase or EvaluationSpec.
It neither imports private validators nor computes reference business answers.
"""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from langchain.agents.middleware import AgentMiddleware, AgentState, hook_config
from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool
from langgraph.runtime import Runtime

from harnesslab.harnesses.base import HarnessRequest
from harnesslab.harnesses.framework_agents import _parse_final_output
from harnesslab.models import TraceEventKind
from harnesslab.reproducibility import canonical_sha256
from harnesslab.tracing import TraceRecorder
from harnesslab.workspace import WorkspaceToolRegistry, snapshot_workspace

RUBRIC_VERSION = "public-contract-v2"
CRITERIA = ("output_contract", "task_semantics", "input_integrity")


class CandidateObserver(AgentMiddleware):
    """Freeze each natural-stop candidate before feedback can modify its workspace."""

    def __init__(self, request: HarnessRequest, trace: TraceRecorder) -> None:
        self.request = request
        self.trace = trace
        self.candidates: list[dict[str, Any]] = []
        self.evidence: list[dict[str, Any]] = []
        self.initial_workspace = (
            snapshot_workspace(request.workspace) if request.workspace is not None else None
        )

    def after_agent(self, state: AgentState, runtime: Runtime) -> None:
        del runtime
        candidate: dict[str, Any] = {"output": _parse_final_output(list(state["messages"]))}
        workspace = self.request.workspace
        if workspace is not None:
            candidate["workspace_snapshot"] = snapshot_workspace(workspace)
            candidate["files"] = {}
            for path in sorted(workspace.rglob("*")):
                if path.is_symlink():
                    raise ValueError("symlink found in candidate workspace")
                if path.is_file() and path.stat().st_size <= 1_000_000:
                    relative = path.relative_to(workspace).as_posix()
                    if any(
                        relative == allowed.strip("/")
                        or relative.startswith(allowed.strip("/") + "/")
                        for allowed in self.request.task.writable_paths
                    ):
                        candidate["files"][relative] = path.read_text(encoding="utf-8")
        candidate["candidate_id"] = canonical_sha256(candidate)
        self.candidates.append(candidate)
        self.trace.emit(
            TraceEventKind.CANDIDATE_COMPLETED,
            "public_candidate",
            payload={"index": len(self.candidates) - 1, "candidate_id": candidate["candidate_id"]},
        )

    def inspect_candidate(self) -> dict[str, Any]:
        """Check the CURRENT candidate's public schema and generic consistency only.

        This does not verify business correctness. Inspect public inputs to check semantics.
        The returned candidate_id binds the evidence to the current immutable snapshot.
        """
        candidate = self.candidates[-1]
        failures: list[str] = []
        value = candidate["output"]
        contract = self.request.task.output_contract
        if contract.get("mode") == "files":
            output_path = str(self.request.task.input.get("output_path", "/output/summary.json"))
            raw = candidate.get("files", {}).get(output_path.lstrip("/"))
            try:
                if raw is None:
                    raise FileNotFoundError(output_path)
                value = json.loads(raw)
            except (ValueError, FileNotFoundError) as exc:
                failures.append(f"output cannot be read as JSON: {exc}")
                value = None
        schema = contract.get("json_schema")
        if schema is not None:
            validator = Draft202012Validator(schema, format_checker=FormatChecker())
            failures.extend(
                f"schema {list(error.absolute_path)}: {error.message}"
                for error in validator.iter_errors(value)
            )
        if isinstance(value, dict):
            try:
                if isinstance(value.get("regions"), list):
                    regions = value["regions"]
                    names = [row["region"] for row in regions]
                    if names != sorted(set(names)):
                        failures.append("regions must be unique and sorted")
                    if Decimal(value["grand_total"]) != sum(
                        (Decimal(row["revenue"]) for row in regions), Decimal(0)
                    ):
                        failures.append("grand_total differs from sum of output revenues")
                if isinstance(value.get("lines"), list) and "subtotal" in value:
                    if Decimal(value["subtotal"]) != sum(
                        (Decimal(row["net"]) for row in value["lines"]), Decimal(0)
                    ):
                        failures.append("subtotal differs from sum of output line nets")
                    if Decimal(value["total"]) != Decimal(value["subtotal"]) + Decimal(
                        value["tax"]
                    ):
                        failures.append("total differs from subtotal plus tax")
                    if Decimal(value["balance"]) != Decimal(value["total"]) - Decimal(
                        value["paid"]
                    ):
                        failures.append("balance differs from total minus paid")
            except (KeyError, TypeError, ValueError, InvalidOperation):
                failures.append("output arithmetic fields are missing or invalid")
        if self.initial_workspace is not None:
            before = self.initial_workspace["files"]
            after = candidate["workspace_snapshot"]["files"]
            if {k: v for k, v in before.items() if k.startswith("input/")} != {
                k: v for k, v in after.items() if k.startswith("input/")
            }:
                failures.append("public input files were modified")
        report = {
            "candidate_id": candidate["candidate_id"],
            "ok": not failures,
            "failures": failures[:30],
            "candidate": value,
            "scope": "public_schema_and_consistency_only; business semantics require review",
        }
        self.evidence.append(report)
        return report

    def read_public_file(self, path: str) -> str:
        """Read public input/output files from this run's isolated workspace, without writes."""
        if self.request.workspace is None:
            raise ValueError("this task has no filesystem; public input is in the transcript")
        reader = WorkspaceToolRegistry(
            self.request.workspace, writable_paths=[], max_calls=1, max_file_size_bytes=100_000
        )
        return reader.read_file(path)

    def evidence_tools(self) -> list[StructuredTool]:
        tools = [StructuredTool.from_function(self.inspect_candidate)]
        if self.request.workspace is not None:
            tools.append(StructuredTool.from_function(self.read_public_file))
        return tools


class GenericRetryMiddleware(AgentMiddleware):
    """Fixed-count generic revisions, without a judge or any validator feedback."""

    def __init__(self, iterations: int) -> None:
        self.iterations = iterations
        self.stops = 0

    @hook_config(can_jump_to=["model"])
    def after_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        del state, runtime
        self.stops += 1
        if self.stops >= self.iterations:
            return None
        return {
            "messages": [
                HumanMessage(
                    "Review your current candidate against the original public task. "
                    "Correct any mistakes and return the required deliverable again. "
                    "Re-read any output files you need. No external verdict is available."
                )
            ],
            "jump_to": "model",
        }


def public_rubric(request: HarnessRequest, *, evidence_tools: bool) -> str:
    lines = [
        "Use exactly the following criterion names, one evaluation for each:",
        "- output_contract: The actual latest deliverable satisfies the PUBLIC output contract.",
        "- task_semantics: It correctly implements EVERY requirement in the original public task, "
        "using only the public input. Check values and edge conditions, not completion claims.",
        "- input_integrity: Public input files were not modified (pass if no workspace exists).",
    ]
    if evidence_tools:
        lines.append(
            "- current_evidence: Call inspect_candidate for THIS candidate before judging; "
            "it must return ok=true. Inspect the returned candidate and read public files "
            "as needed. Tool checks cover schema/consistency, NOT full business correctness."
        )
    lines.append("Original public instruction: " + request.task.instruction)
    return "\n".join(lines)


def runtime_gate(
    evaluations: list[dict[str, Any]], observer: CandidateObserver, *, evidence_tools: bool
) -> bool:
    if not evaluations or not observer.candidates or evaluations[-1]["result"] != "satisfied":
        return False
    criteria = evaluations[-1].get("criteria", [])
    required = set(CRITERIA) | ({"current_evidence"} if evidence_tools else set())
    if {item["name"] for item in criteria if item["passed"]} != required:
        return False
    if evidence_tools:
        return any(
            item["candidate_id"] == observer.candidates[-1]["candidate_id"] and item["ok"]
            for item in observer.evidence
        )
    return True
