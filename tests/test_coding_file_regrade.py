import asyncio
import json
import shutil
import sys
from types import SimpleNamespace

import pytest
from harbor.models.agent.context import AgentContext

from harnesslab.coding.config import save_json
from harnesslab.coding.regrade import FileSubmissionRegrader, file_submission
from harnesslab.coding.reuse import digest
from harnesslab.coding.submission_delta import capture_delta, snapshot
from harnesslab.coding.submission_restore import restore_file_delta


@pytest.fixture
def saved_files(tmp_path):
    original, fresh, saved = (tmp_path / name for name in ("original", "fresh", "saved"))
    (original / "app").mkdir(parents=True)
    (original / "app/input.txt").write_text("original input")
    shutil.copytree(original, fresh)
    baseline = snapshot(original, ["/app"])
    saved.mkdir()
    save_json(saved / "baseline.json", baseline)
    (original / "app/input.txt").write_text("modified input")
    (original / "app/images").mkdir()
    (original / "app/images/crop.png").write_bytes(bytes(range(256)))
    (original / "app/answer.txt").write_text("saved answer")
    manifest = capture_delta(original, ["/app"], baseline, saved / "submission.tar.gz")
    manifest.update(
        transfer_verified=True,
        source_fingerprint="image",
        template_id="template",
        prerequisites={"capture_paths": ["/app"]},
        actor_user="root",
    )
    save_json(saved / "manifest.json", manifest)
    return original, fresh, saved, baseline, manifest


def test_restore_reproduces_saved_bytes_and_metadata_without_running_them(saved_files):
    original, fresh, saved, baseline, manifest = saved_files
    assert file_submission(saved / "manifest.json", digest(saved / "manifest.json")) == manifest
    result = restore_file_delta(fresh, baseline, manifest, saved / "submission.tar.gz")
    assert result == {"restored_files": 3, "model_calls": 0}
    assert snapshot(fresh, ["/app"]) == snapshot(original, ["/app"])


@pytest.mark.parametrize(
    "problem", ["deleted", "volatile", "symlink", "archive", "baseline", "missing", "changed"]
)
def test_file_submission_rejects_incomplete_or_altered_evidence(saved_files, problem):
    _, _, saved, _, manifest = saved_files
    if problem == "deleted":
        manifest["removed"] = ["/app/input.txt"]
    elif problem == "volatile":
        manifest["changed_during_capture"] = ["/app/input.txt"]
    elif problem == "symlink":
        manifest["changed"]["/app/input.txt"]["kind"] = "symlink"
    elif problem == "archive":
        (saved / "submission.tar.gz").write_bytes(b"changed")
    elif problem == "baseline":
        save_json(saved / "baseline.json", {})
    elif problem == "missing":
        manifest["changed"]["/app/extra.txt"] = manifest["changed"]["/app/input.txt"]
    else:
        manifest["changed"]["/app/input.txt"]["sha256"] = "changed"
    save_json(saved / "manifest.json", manifest)
    with pytest.raises(ValueError):
        file_submission(saved / "manifest.json", digest(saved / "manifest.json"))


def test_restore_requires_the_identical_starting_filesystem(saved_files):
    _, fresh, saved, baseline, manifest = saved_files
    (fresh / "app/input.txt").write_text("another task input")
    with pytest.raises(ValueError, match="baseline"):
        restore_file_delta(fresh, baseline, manifest, saved / "submission.tar.gz")
    assert not (fresh / "app/answer.txt").exists()


def test_file_regrader_restores_then_recaptures_before_official_verification(
    saved_files, tmp_path, monkeypatch
):
    _, fresh, saved, baseline, manifest = saved_files
    writes = {}
    monkeypatch.setitem(
        sys.modules,
        "harnesslab.coding.native_environment",
        SimpleNamespace(CONTROL="/opt/harnesslab-controller"),
    )

    async def write(name, content):
        writes[name.rsplit("/", 1)[-1]] = content

    class Environment:
        entry = manifest["prerequisites"]
        _source_fingerprint = manifest["source_fingerprint"]
        _template_name = manifest["template_id"]
        actor_user = manifest["actor_user"]
        _sandbox = SimpleNamespace(files=SimpleNamespace(write=write))

        async def begin_actor(self, network, logs):
            assert network == "offline"
            save_json(logs / "submission/baseline.json", snapshot(fresh, ["/app"]))

        async def upload_archive(self, path, expected, destination):
            assert digest(path) == expected and destination.endswith("saved-submission.tar.gz")
            self.archive = path

        async def python_command(self, code, timeout):
            assert "restore_file_delta" in code and timeout == 300
            assert "from submission_delta" in writes["submission_restore.py"]
            result = restore_file_delta(
                fresh, baseline, json.loads(writes["saved-manifest.json"]), self.archive
            )
            return SimpleNamespace(stdout=json.dumps(result))

        async def end_actor(self, logs):
            record = capture_delta(fresh, ["/app"], baseline, logs / "submission/submission.tar.gz")
            record.update(
                {
                    key: manifest[key]
                    for key in (
                        "transfer_verified",
                        "source_fingerprint",
                        "template_id",
                        "prerequisites",
                        "actor_user",
                    )
                }
            )
            save_json(logs / "submission/manifest.json", record)

    logs = tmp_path / "agent"
    logs.mkdir()
    agent = FileSubmissionRegrader(
        logs_dir=logs,
        network_mode="offline",
        source_manifest=str(saved / "manifest.json"),
        source_sha256=digest(saved / "manifest.json"),
    )
    context = AgentContext()
    environment = Environment()
    asyncio.run(agent.setup(environment))
    asyncio.run(agent.run("ignored", environment, context))
    assert context.metadata["method"] == "restored-filesystem-submission"
    assert context.metadata["model_calls"] == 0
    assert context.metadata["source_sha256"] == digest(saved / "manifest.json")
    assert json.loads((logs / "restore-result.json").read_text())["restored_files"] == 3
