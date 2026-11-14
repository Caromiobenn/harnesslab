"""Exercise evidence freshness and real graph repair control without a host shell."""

import hashlib
import json
import shlex
from types import SimpleNamespace

import pytest
from deepagents import create_deep_agent
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

pytest.importorskip("harbor")

from harnesslab.coding.review import ReviewLedger, build_review


class MemoryBackend:
    def __init__(self):
        self.files = {"/app/code.py": b"first version"}
        self.commands = []

    def execute(self, command):
        self.commands.append(command)
        if command.startswith("python3 -c "):
            paths = json.loads(shlex.split(command)[-1])
            result = {}
            for path in paths:
                content = self.files.get(path)
                result[path] = (
                    {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}
                    if content is not None
                    else {"error": "not a regular file"}
                )
            return SimpleNamespace(output=json.dumps(result), exit_code=0)
        return SimpleNamespace(
            output="1 passed" if command == "check" else "1 failed",
            exit_code=0 if command == "check" else 1,
        )


class Trace:
    def emit(self, *args, **kwargs):
        pass


class ToolModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def verdict():
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "GraderResponse",
                "id": "verdict",
                "args": {
                    "result": "satisfied",
                    "explanation": "All requirements satisfied.",
                    "criteria": [
                        {"name": name, "passed": True}
                        for name in ("deliverables", "behavior", "verification", "current_evidence")
                    ],
                },
            }
        ],
    )


def verification():
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "verify_candidate",
                "id": "check",
                "args": {
                    "command": "check",
                    "artifacts": ["/app/code.py"],
                },
            }
        ],
    )


def test_evidence_invalidates_when_artifact_changes_or_candidate_advances(tmp_path):
    backend = MemoryBackend()
    ledger = ReviewLedger(backend, tmp_path, Trace())
    ledger.freeze([AIMessage(content="done")])
    ledger.verify_candidate("check", ["/app/code.py"])
    assert ledger.current_evidence()[0]
    backend.files["/app/code.py"] = b"changed after test"
    assert not ledger.current_evidence()[0]
    ledger.freeze([AIMessage(content="done again")])
    assert not ledger.current_evidence()[0]


def test_failed_check_cannot_be_hidden_by_later_passing_check(tmp_path):
    ledger = ReviewLedger(MemoryBackend(), tmp_path, Trace())
    ledger.freeze([AIMessage(content="done")])
    ledger.verify_candidate("fail", ["/app/code.py"])
    ledger.verify_candidate("check", ["/app/code.py"])
    assert not ledger.current_evidence()[0]


def test_real_graph_rejects_false_satisfied_and_repairs_with_fresh_evidence(tmp_path):
    grader = ToolModel(messages=iter([verdict(), verification(), verdict()]))
    middleware, inputs, ledger = build_review(
        "rubric_evidence", grader, MemoryBackend(), tmp_path, Trace(), 3, "Implement code.py"
    )
    actor = ToolModel(messages=iter([AIMessage(content="first"), AIMessage(content="repaired")]))
    agent = create_deep_agent(model=actor, middleware=middleware)
    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Implement code.py"}], **inputs}
    )
    assert len(ledger.candidates) == 2
    assert [item["accepted"] for item in ledger.gates] == [False, True]
    assert ledger.evidence[0]["candidate_id"] == ledger.candidates[-1]["candidate_id"]
    assert ledger.outcomes[-1]["status"] == "satisfied"
    assert result["messages"][-1].content == "repaired"


def test_real_graph_stops_after_three_unsupported_verdicts(tmp_path):
    middleware, inputs, ledger = build_review(
        "rubric_evidence",
        ToolModel(messages=iter([verdict(), verdict(), verdict()])),
        MemoryBackend(),
        tmp_path,
        Trace(),
        3,
        "Implement code.py",
    )
    actor = ToolModel(messages=iter([AIMessage(content=str(index)) for index in range(3)]))
    agent = create_deep_agent(model=actor, middleware=middleware)
    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Implement code.py"}], **inputs}
    )
    assert len(ledger.candidates) == 3
    assert ledger.outcomes[-1]["status"] == "max_iterations_reached"
    assert result["messages"][-1].content == "2"
    assert all(not item["accepted"] for item in ledger.gates)


def test_generic_retry_uses_three_candidates_without_grader(tmp_path):
    middleware, inputs, ledger = build_review(
        "generic_retry", None, MemoryBackend(), tmp_path, Trace(), 3, "Implement code.py"
    )
    actor = ToolModel(messages=iter([AIMessage(content=str(index)) for index in range(3)]))
    result = create_deep_agent(model=actor, middleware=middleware).invoke(
        {
            "messages": [{"role": "user", "content": "Implement code.py"}],
            **inputs,
        }
    )
    assert len(ledger.candidates) == 3
    assert not ledger.evaluations
    assert result["messages"][-1].content == "2"
