import json
from types import SimpleNamespace

import pytest
from langchain_core.runnables import RunnableLambda

from harnesslab.coding import observability as ob
from harnesslab.coding.config import CodingConfig
from harnesslab.coding.metrics import trial_metrics


class RecordedClient:
    def __init__(self, **kwargs):
        self.options = kwargs
        self.created = []
        self.updated = []
        self.feedback = []

    def create_run(self, **kwargs):
        self.created.append(kwargs)

    def update_run(self, *args, **kwargs):
        self.updated.append(kwargs)

    def flush(self, **kwargs):
        pass

    def read_run(self, run_id):
        if getattr(self, "index_pending", False):
            self.index_pending = False
            raise ob.LangSmithNotFoundError("index pending")
        return SimpleNamespace(id=run_id)

    def get_run_url(self, **kwargs):
        return "https://smith.langchain.com/fixture"

    def create_feedback(self, **kwargs):
        self.feedback.append(kwargs)


@pytest.mark.parametrize(
    "group",
    [
        "deepagents_default",
        "generic_retry",
        "rubric_transcript",
        "rubric_evidence",
    ],
)
def test_four_groups_trace_nested_work_and_publish_official_feedback(tmp_path, monkeypatch, group):
    client = RecordedClient()
    client.index_pending = True
    monkeypatch.setattr(ob.time, "sleep", lambda _: None)
    monkeypatch.setattr(ob, "tracing_client", lambda root: (client, "fixture"))
    config = CodingConfig(
        benchmark="terminal-bench-2.1",
        revision="fixture",
        tasks=["fixture"],
        groups=[group],
        purpose="test",
        langsmith_tracing=True,
    )
    folder = tmp_path / "trial/agent"
    folder.mkdir(parents=True)
    observation = ob.StudyTrace(tmp_path, folder, "fixture", group, config, "test-model")
    child = RunnableLambda(lambda value: value + 1)
    parent = RunnableLambda(lambda value: child.invoke(value))
    assert parent.invoke(1, config={**observation.config, "callbacks": [observation.tracer]}) == 2
    observation.finish()
    root = next(row for row in client.created if str(row["id"]) == str(observation.run_id))
    assert root["extra"]["metadata"]["group"] == group
    assert any(str(row.get("parent_run_id")) == str(observation.run_id) for row in client.created)
    assert json.loads((folder / "langsmith.json").read_text())["status"] == "uploaded"
    metrics = trial_metrics(folder.parent, {})
    result = ob.publish_trial(
        tmp_path,
        folder.parent,
        {
            "metrics": metrics,
            "reward": 0,
            "pipeline_ok": True,
        },
    )
    scores = {row["key"]: row["score"] for row in client.feedback}
    assert scores["official_reward"] == 0 and scores["pipeline_ok"] == 1
    assert "input_tokens" not in scores
    assert result["feedback_status"] == "uploaded"


def test_credentials_are_loaded_explicitly_and_missing_key_is_reported(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="LANGSMITH_API_KEY"):
        ob.tracing_client(tmp_path)
    (tmp_path / ".env").write_text("LANGSMITH_API_KEY=test-only\nLANGSMITH_PROJECT=test\n")
    monkeypatch.setattr(ob, "Client", RecordedClient)
    client, project = ob.tracing_client(tmp_path)
    assert client.options["api_key"] == "test-only" and project == "test"
    assert ob.publish_trial(tmp_path, tmp_path / "untraced-mini", {}) is None


def test_upload_failure_keeps_local_record(tmp_path, monkeypatch):
    client = RecordedClient()
    monkeypatch.setattr(ob, "tracing_client", lambda root: (client, "fixture"))
    config = CodingConfig(
        benchmark="terminal-bench-2.1", revision="fixture", tasks=["fixture"], purpose="test"
    )
    observation = ob.StudyTrace(tmp_path, tmp_path, "fixture", "generic_retry", config, "test")

    def failed(**kwargs):
        raise ConnectionError("fixture")

    monkeypatch.setattr(client, "flush", failed)
    observation.finish()
    assert json.loads((tmp_path / "langsmith.json").read_text())["error_type"] == "ConnectionError"
