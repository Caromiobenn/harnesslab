import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
spec = importlib.util.spec_from_file_location(
    "regrade_observability",
    Path(__file__).resolve().parents[1] / "scripts/publish_coding_regrades.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize("started,received,complete", [(5, 4, 0), (4, 4, 1), (None, 4, None)])
def test_regrade_feedback_preserves_original_failure_and_usage(
    tmp_path, monkeypatch, started, received, complete
):
    agent = tmp_path / "trial/agent"
    agent.mkdir(parents=True)
    trace = agent / "langsmith.json"
    trace.write_text(json.dumps({"run_id": str(uuid4()), "status": "uploaded"}))
    old_feedback = agent / "langsmith-metrics.json"
    old_feedback.write_text('{"verified":true,"measurements":{"pipeline_ok":0}}')
    source = tmp_path / "outcome.json"
    source.write_text(
        json.dumps(
            {
                "reward": None,
                "pipeline_ok": False,
                "trial": str(agent.parent),
                "exception": {"exception_type": "APITimeoutError"},
                "agent_result": {"metadata": {"started_model_calls": started}},
                "metrics": {
                    "model_responses": received,
                    "tokens_and_lengths": {"input_tokens": 100},
                },
            }
        )
    )
    row = {
        "cell": ["offline", "task", "default", 0],
        "reward": 0,
        "source": {"outcome_sha256": hashlib.sha256(source.read_bytes()).hexdigest()},
        "regrade": {"trial": "regrade-trial"},
    }
    monkeypatch.setattr(module, "regrade_scores", lambda paths: {source: row})
    observed = []
    client = SimpleNamespace(
        read_run=lambda identity: object(),
        get_run_url=lambda **kwargs: "https://smith.langchain.com/fixture",
    )
    monkeypatch.setattr(module, "tracing_client", lambda root: (client, "fixture"))

    def record(client, run, identity, values):
        observed.append(values)
        return True

    monkeypatch.setattr(module, "persist_feedback", record)
    saved = {path: path.read_bytes() for path in (source, trace, old_feedback)}
    for _ in range(2):
        result = module.publish(tmp_path, [], tmp_path / "regrade-feedback.json")
        assert result["ok"] and result["model_calls"] == 0
    assert observed[0] == observed[1]
    assert observed[0]["official_reward"]["score"] == 0
    assert "pipeline_ok" not in observed[0] and "input_tokens" not in observed[0]
    assert observed[0].get("usage_complete", {}).get("score") == complete
    assert all(path.read_bytes() == content for path, content in saved.items())


def test_publication_stops_before_network_on_invalid_regrade(tmp_path, monkeypatch):
    def invalid(paths):
        raise ValueError("Regraded source outcome changed")

    monkeypatch.setattr(module, "regrade_scores", invalid)
    monkeypatch.setattr(module, "tracing_client", lambda root: pytest.fail("must validate first"))
    with pytest.raises(ValueError, match="outcome changed"):
        module.publish(tmp_path, [], tmp_path / "receipt.json")


def test_publication_does_not_replace_existing_score(tmp_path, monkeypatch):
    source = tmp_path / "outcome.json"
    source.write_text('{"reward":1}')
    monkeypatch.setattr(module, "regrade_scores", lambda paths: {source: {}})
    monkeypatch.setattr(module, "tracing_client", lambda root: (None, "fixture"))
    with pytest.raises(ValueError, match="existing official score"):
        module.publish(tmp_path, [], tmp_path / "receipt.json")
