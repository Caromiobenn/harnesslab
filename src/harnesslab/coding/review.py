"""Public-task review and fresh, artifact-bound evidence inside the task environment."""

from __future__ import annotations

import hashlib
import json
import shlex
import threading
from pathlib import Path

from deepagents.middleware.rubric import GRADER_SYSTEM_PROMPT, RubricMiddleware
from langchain.agents.middleware import AgentMiddleware, AgentState, hook_config
from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool

from harnesslab.coding.config import save_json
from harnesslab.harnesses.verification import GenericRetryMiddleware

CRITERIA = ("deliverables", "behavior", "verification")


class ReviewLedger:
    def __init__(self, backend, folder: Path, trace):
        self.backend = backend
        self.folder = folder
        self.trace = trace
        self.lock = threading.Lock()
        self.candidates: list[dict] = []
        self.evidence: list[dict] = []
        self.evaluations: list[dict] = []
        self.gates: list[dict] = []
        self.outcomes: list[dict] = []

    def record(self, kind: str, record: dict) -> None:
        with self.lock:
            getattr(self, kind).append(record)
            save_json(
                self.folder / "review.json",
                {
                    name: getattr(self, name)
                    for name in ("candidates", "evidence", "evaluations", "gates", "outcomes")
                },
            )
        self.trace.emit("review_" + kind, record)

    @property
    def candidate_id(self) -> str:
        return self.candidates[-1]["candidate_id"]

    def freeze(self, messages) -> None:
        content = str(messages[-1].content)
        index = len(self.candidates)
        digest = hashlib.sha256(content.encode()).hexdigest()
        self.record(
            "candidates",
            {"candidate_id": f"{index}:{digest}", "index": index, "final_message": content},
        )

    def snapshot(self, artifacts: list[str]) -> dict:
        if not artifacts or len(artifacts) > 64 or any(not p.startswith("/") for p in artifacts):
            raise ValueError("Supply 1-64 absolute artifact file paths, not directories")
        script = """import hashlib,json,sys
from pathlib import Path
result={}
for name in json.loads(sys.argv[1]):
    path=Path(name)
    if not path.is_file():
        result[name]={"error":"not a regular file"}
        continue
    digest=hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda:stream.read(1048576),b""):
            digest.update(chunk)
    result[name]={"sha256":digest.hexdigest(),"bytes":path.stat().st_size}
print(json.dumps(result))
"""
        command = "python3 -c " + shlex.quote(script) + " " + shlex.quote(json.dumps(artifacts))
        result = self.backend.execute(command)
        if result.exit_code != 0:
            raise RuntimeError("Could not fingerprint artifacts: " + result.output[-2000:])
        return json.loads(result.output)

    def read_artifact(self, path: str) -> dict:
        """Read a public artifact in the current sandbox; return text and its content hash."""
        manifest = self.snapshot([path])
        if "error" in manifest[path]:
            return {"candidate_id": self.candidate_id, "artifact": manifest}
        text = self.backend.read(path, offset=0, limit=200)
        record = {
            "candidate_id": self.candidate_id,
            "kind": "read",
            "artifacts": manifest,
            "content": text.file_data,
            "error": text.error,
        }
        self.record("evidence", record)
        return record

    def verify_candidate(self, command: str, artifacts: list[str]) -> dict:
        """Run a public behavior/test command and bind its result to the listed deliverable files.

        Include the actual implementation/output files that the check covers. Use meaningful
        visible tests or direct behavior checks. Do not repair files in this tool: return gaps
        to the working agent. Official evaluator tests are unavailable during review.
        """
        before = self.snapshot(artifacts)
        result = self.backend.execute(command)
        after = self.snapshot(artifacts)
        record = {
            "candidate_id": self.candidate_id,
            "kind": "verification",
            "command": command,
            "exit_code": result.exit_code,
            "output": result.output,
            "before": before,
            "after": after,
            "passed": result.exit_code == 0
            and before == after
            and all("sha256" in value for value in after.values()),
        }
        self.record("evidence", record)
        return record

    def current_evidence(self) -> tuple[bool, str]:
        records = [
            item
            for item in self.evidence
            if item["candidate_id"] == self.candidate_id and item["kind"] == "verification"
        ]
        if not records:
            return False, "No public verification command was run for this candidate."
        # A later failing check must not be hidden by selecting an earlier passing check.
        if not all(item["passed"] for item in records):
            return False, "A verification failed or modified its declared deliverable files."
        for item in records:
            if self.snapshot(list(item["after"])) != item["after"]:
                return False, "Artifact content changed after the verification command."
        return True, "Current checks passed on unchanged declared artifacts."

    def tools(self) -> list[StructuredTool]:
        return [
            StructuredTool.from_function(self.read_artifact),
            StructuredTool.from_function(self.verify_candidate),
        ]


class CandidateObserver(AgentMiddleware):
    def __init__(self, ledger: ReviewLedger):
        self.ledger = ledger

    def after_agent(self, state: AgentState, runtime):
        del runtime
        self.ledger.freeze(state["messages"])


class ReviewOutcome(AgentMiddleware):
    """Capture internal rubric state before the framework omits it from public output."""

    def __init__(self, ledger: ReviewLedger):
        self.ledger = ledger

    def after_agent(self, state: AgentState, runtime):
        del runtime
        self.ledger.record(
            "outcomes",
            {
                "candidate_id": self.ledger.candidate_id,
                "status": state.get("_rubric_status", "completed"),
                "iterations": len(self.ledger.candidates),
            },
        )


class EvidenceGate(AgentMiddleware):
    """Reject an unsupported 'satisfied' verdict and actually request another repair."""

    def __init__(self, ledger: ReviewLedger, iterations: int):
        self.ledger = ledger
        self.iterations = iterations

    @hook_config(can_jump_to=["model"])
    def after_agent(self, state: AgentState, runtime):
        del runtime
        if state.get("_rubric_status") != "satisfied":
            return None
        evaluation = self.ledger.evaluations[-1]
        passed = {item["name"] for item in evaluation["criteria"] if item["passed"]}
        required = set(CRITERIA) | {"current_evidence"}
        ok, reason = self.ledger.current_evidence()
        if not required <= passed:
            ok, reason = False, "The grader did not pass every required criterion."
        self.ledger.record(
            "gates", {"candidate_id": self.ledger.candidate_id, "accepted": ok, "reason": reason}
        )
        if ok:
            return None
        if len(self.ledger.candidates) >= self.iterations:
            return {"_rubric_status": "max_iterations_reached"}
        return {
            "_rubric_status": "needs_revision",
            "jump_to": "model",
            "messages": [
                HumanMessage(
                    "The evidence review could not accept this candidate: "
                    + reason
                    + " Inspect the current files and checks, repair as needed, then finish."
                )
            ],
        }


def build_review(
    group: str, model, backend, folder: Path, trace, iterations: int, instruction: str
) -> tuple[list, dict, ReviewLedger | None]:
    if group == "deepagents_default":
        return [], {}, None
    ledger = ReviewLedger(backend, folder, trace)
    observer = CandidateObserver(ledger)
    outcome = ReviewOutcome(ledger)
    if group == "generic_retry":
        return [outcome, GenericRetryMiddleware(iterations), observer], {}, ledger
    evidence = group == "rubric_evidence"
    if group not in ("rubric_transcript", "rubric_evidence"):
        raise ValueError(group)
    rubric = "\n".join(
        [
            "Use exactly these criterion names and assess every requirement of the public task:",
            "- deliverables: The required files/results exist at the requested paths and formats.",
            "- behavior: The implementation meets the public requirements and edge cases.",
            "- verification: Visible tests or direct behavior checks support completion.",
            *(
                [
                    "- current_evidence: Call verify_candidate for this candidate. Include actual "
                    "deliverable files; every check must pass and leave their contents unchanged."
                ]
                if evidence
                else []
            ),
            "Original public task:\n" + instruction,
        ]
    )
    grader = RubricMiddleware(
        model=model,
        tools=ledger.tools() if evidence else [],
        max_iterations=iterations,
        system_prompt=GRADER_SYSTEM_PROMPT + "\nA candidate defect requires needs_revision "
        "with actionable gaps. Reserve failed for an uninterpretable rubric. "
        "Assess all named criteria. Do not infer success from completion claims. "
        "Verification commands must inspect public behavior, without repairing deliverables. "
        "Return needed repairs to the working agent. Runtime review is not the official score.",
        on_evaluation=lambda result: ledger.record("evaluations", dict(result)),
    )
    # after_agent hooks run in reverse: freeze -> grade -> enforce evidence -> finish.
    middleware = [EvidenceGate(ledger, iterations)] if evidence else []
    return [outcome, *middleware, grader, observer], {"rubric": rubric}, ledger
