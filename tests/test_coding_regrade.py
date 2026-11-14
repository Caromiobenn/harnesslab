import asyncio
import shutil

import pytest

pytest.importorskip("harbor")

from harbor.models.agent.context import AgentContext

from harnesslab.coding.config import save_json
from harnesslab.coding.regrade import UnchangedSubmissionRegrader, unchanged_submission
from harnesslab.coding.reuse import digest
from harnesslab.coding.submission_delta import capture_delta, snapshot


@pytest.fixture
def saved(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / "app").mkdir(parents=True)
    (workspace / "app/input.txt").write_text("unchanged input")
    source = tmp_path / "saved"
    source.mkdir()
    baseline = snapshot(workspace, ["/app"])
    save_json(source / "baseline.json", baseline)
    manifest = capture_delta(workspace, ["/app"], baseline, source / "submission.tar.gz")
    manifest.update(
        transfer_verified=True,
        source_fingerprint="image",
        template_id="template",
        prerequisites={"capture_paths": ["/app"]},
        actor_user="root",
    )
    save_json(source / "manifest.json", manifest)
    return source, manifest


class Environment:
    def __init__(self, source, manifest):
        self.source = source
        self.entry = manifest["prerequisites"]
        self._source_fingerprint = manifest["source_fingerprint"]
        self._template_name = manifest["template_id"]
        self.actor_user = manifest["actor_user"]
        self.finished = False

    async def begin_actor(self, network, logs):
        assert network == "offline"
        (logs / "submission").mkdir()
        shutil.copyfile(self.source / "baseline.json", logs / "submission/baseline.json")

    async def end_actor(self, logs):
        self.finished = True
        for name in ("manifest.json", "submission.tar.gz"):
            shutil.copyfile(self.source / name, logs / "submission" / name)


def test_regrader_checks_fresh_baseline_and_preserves_source_provenance(saved, tmp_path):
    source, manifest = saved
    environment = Environment(source, manifest)
    logs = tmp_path / "agent"
    logs.mkdir()
    agent = UnchangedSubmissionRegrader(
        logs_dir=logs,
        network_mode="offline",
        source_manifest=str(source / "manifest.json"),
        source_sha256=digest(source / "manifest.json"),
    )
    context = AgentContext()
    asyncio.run(agent.setup(environment))
    asyncio.run(agent.run("ignored", environment, context))
    assert environment.finished
    assert context.metadata["model_calls"] == 0
    assert context.metadata["source_sha256"] == digest(source / "manifest.json")
    assert context.metadata["baseline_sha256"] == manifest["baseline_sha256"]


@pytest.mark.parametrize(
    "field", ["changed", "removed", "archived_files", "changed_during_capture", "special_paths"]
)
def test_unchanged_regrader_rejects_changed_or_incomplete_submissions(saved, field):
    source, manifest = saved
    manifest[field] = ["/app/changed"]
    save_json(source / "manifest.json", manifest)
    with pytest.raises(ValueError, match="unchanged filesystem"):
        unchanged_submission(source / "manifest.json", digest(source / "manifest.json"))


@pytest.mark.parametrize("target", ["baseline.json", "submission.tar.gz"])
def test_unchanged_regrader_rejects_modified_saved_bytes(saved, target):
    source, _ = saved
    (source / target).write_text("{}")
    with pytest.raises(ValueError):
        unchanged_submission(source / "manifest.json", digest(source / "manifest.json"))


@pytest.mark.parametrize("mismatch", ["image", "baseline"])
def test_unchanged_regrader_rejects_a_different_fresh_environment(saved, tmp_path, mismatch):
    source, manifest = saved
    environment = Environment(source, manifest)
    if mismatch == "image":
        environment._source_fingerprint = "different image"
    else:
        original = environment.begin_actor

        async def different(network, logs):
            await original(network, logs)
            save_json(logs / "submission/baseline.json", {})

        environment.begin_actor = different
    logs = tmp_path / "agent"
    logs.mkdir()
    agent = UnchangedSubmissionRegrader(
        logs_dir=logs,
        network_mode="offline",
        source_manifest=str(source / "manifest.json"),
        source_sha256=digest(source / "manifest.json"),
    )
    with pytest.raises(ValueError):
        asyncio.run(agent.setup(environment))
    assert not environment.finished
