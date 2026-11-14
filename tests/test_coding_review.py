"""Exercise evidence freshness and real graph repair control without a host shell."""

import base64
import hashlib
import json
import shlex
from types import SimpleNamespace

import pytest
from deepagents import create_deep_agent
from langchain_core.callbacks import BaseCallbackHandler
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


class ReadBackend(MemoryBackend):
    def __init__(self):
        super().__init__()
        self.check_output = "1 passed"

    def read(self, path, offset, limit):
        assert offset == 0 and limit == 200
        content = self.files[path]
        try:
            data = {"content": content.decode("utf-8"), "encoding": "utf-8"}
        except UnicodeDecodeError:
            data = {"content": base64.b64encode(content).decode(), "encoding": "base64"}
        return SimpleNamespace(file_data=data, error=None)

    def execute(self, command):
        result = super().execute(command)
        if command == "check":
            result.output = self.check_output
        return result


def test_binary_preview_omits_payload_and_preserves_full_evidence(tmp_path):
    backend = ReadBackend()
    backend.files["/app/dist.npy"] = b"\x93NUMPY" + bytes(1200122)
    ledger = ReviewLedger(backend, tmp_path, Trace(), output_max_chars=32768)
    ledger.freeze([AIMessage(content="candidate")])
    returned = ledger.read_artifact("/app/dist.npy")
    assert returned["content_omitted"] and returned["content"]["content"] == ""
    assert returned["original_content_chars"] == 1600172
    assert returned["artifacts"]["/app/dist.npy"]["bytes"] == 1200128
    assert len(json.dumps(returned)) < 1000
    saved = json.loads((tmp_path / "review.json").read_text())["evidence"][0]
    assert base64.b64decode(saved["content"]["content"]) == backend.files["/app/dist.npy"]
    assert not ledger.current_evidence()[0]


def test_text_preview_caps_a_single_long_line_and_leaves_short_reads_unchanged(tmp_path):
    backend = ReadBackend()
    backend.files["/app/long.txt"] = ("词" * 50000).encode()
    ledger = ReviewLedger(backend, tmp_path, Trace(), output_max_chars=32768)
    ledger.freeze([AIMessage(content="candidate")])
    returned = ledger.read_artifact("/app/long.txt")
    assert len(returned["content"]["content"]) == 32768
    assert returned["content_truncated"] and not returned["content_omitted"]
    assert returned["original_content_chars"] == 50000
    assert len(ledger.evidence[0]["content"]["content"]) == 50000
    short = ledger.read_artifact("/app/code.py")
    assert short["content"]["content"] == "first version" and not short["content_truncated"]


def test_verification_preview_retains_exit_status_hashes_and_full_stdout(tmp_path):
    backend = ReadBackend()
    backend.check_output = "check result\n" * 10000
    ledger = ReviewLedger(backend, tmp_path, Trace(), output_max_chars=32768)
    ledger.freeze([AIMessage(content="candidate")])
    returned = ledger.verify_candidate("check", ["/app/code.py"])
    assert returned["passed"] and returned["exit_code"] == 0
    assert returned["output_truncated"] and len(returned["output"]) == 32768
    assert ledger.evidence[0]["output"] == backend.check_output
    assert returned["after"] == ledger.evidence[0]["after"]
    assert ledger.current_evidence()[0]
    backend.files["/app/code.py"] = b"later change"
    assert not ledger.current_evidence()[0]


def test_zero_preview_limit_preserves_legacy_binary_result(tmp_path):
    backend = ReadBackend()
    backend.files["/app/binary"] = b"\xff" * 16
    ledger = ReviewLedger(backend, tmp_path, Trace())
    ledger.freeze([AIMessage(content="candidate")])
    returned = ledger.read_artifact("/app/binary")
    assert returned is ledger.evidence[0]
    assert returned["content"]["content"] == base64.b64encode(b"\xff" * 16).decode()


def test_real_grader_graph_keeps_large_binary_out_of_followup_request(tmp_path):
    class RequestCapture(BaseCallbackHandler):
        def __init__(self):
            self.sizes = []

        def on_chat_model_start(self, serialized, messages, **kwargs):
            self.sizes.extend(
                len(json.dumps([m.model_dump(mode="json") for m in batch])) for batch in messages
            )

    backend = ReadBackend()
    backend.files["/app/dist.npy"] = b"\x93NUMPY" + bytes(1200122)
    read = AIMessage(
        content="",
        tool_calls=[
            {"name": "read_artifact", "id": "read-binary", "args": {"path": "/app/dist.npy"}}
        ],
    )
    check = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "verify_candidate",
                "id": "check-binary",
                "args": {"command": "check", "artifacts": ["/app/dist.npy"]},
            }
        ],
    )
    grader = ToolModel(messages=iter([read, check, verdict()]))
    middleware, inputs, ledger = build_review(
        "rubric_evidence",
        grader,
        backend,
        tmp_path,
        Trace(),
        3,
        "Check the distribution file.",
        output_max_chars=32768,
    )
    actor = ToolModel(messages=iter([AIMessage(content="candidate")]))
    capture = RequestCapture()
    create_deep_agent(model=actor, middleware=middleware).invoke(
        {"messages": [{"role": "user", "content": "Check the file."}], **inputs},
        config={"callbacks": [capture]},
    )
    assert capture.sizes and max(capture.sizes) < 100000
    assert ledger.gates[-1]["accepted"] and ledger.outcomes[-1]["status"] == "satisfied"
    assert ledger.evidence[0]["artifacts"]["/app/dist.npy"]["bytes"] == 1200128
