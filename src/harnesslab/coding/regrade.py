"""Regrade a verified unchanged filesystem submission without an actor request."""

import hashlib
import json
import tarfile
from pathlib import Path

from harnesslab.coding.config import save_json
from harnesslab.coding.controls import NativeEmptyControl
from harnesslab.coding.reuse import checked_json, digest


def unchanged_submission(path: Path, expected_sha: str) -> dict:
    manifest = checked_json(path, expected_sha)
    if (
        manifest["format"] != "filesystem-delta-v1"
        or not manifest["transfer_verified"]
        or any(
            manifest[key]
            for key in (
                "changed",
                "removed",
                "archived_files",
                "changed_during_capture",
                "special_paths",
            )
        )
    ):
        raise ValueError("This regrader requires a complete unchanged filesystem submission")
    baseline = json.loads((path.parent / "baseline.json").read_text())
    if (
        hashlib.sha256(json.dumps(baseline, sort_keys=True).encode()).hexdigest()
        != manifest["baseline_sha256"]
    ):
        raise ValueError("Saved baseline changed")
    archive = path.parent / manifest["archive"]
    if digest(archive) != manifest["sha256"] or archive.stat().st_size != manifest["bytes"]:
        raise ValueError("Saved submission archive changed")
    with tarfile.open(archive) as source:
        if source.getmembers():
            raise ValueError("An unchanged submission cannot contain archived changes")
    return manifest


class UnchangedSubmissionRegrader(NativeEmptyControl):
    validate_submission = staticmethod(unchanged_submission)
    method = "unchanged-filesystem-submission"

    @staticmethod
    def name():
        return "harnesslab-unchanged-submission-regrader"

    def __init__(self, *args, source_manifest, source_sha256, **kwargs):
        super().__init__(*args, **kwargs)
        self.source_manifest = Path(source_manifest)
        self.source_sha256 = source_sha256

    async def setup(self, environment):
        self.saved = self.validate_submission(self.source_manifest, self.source_sha256)
        if (
            environment.entry != self.saved["prerequisites"]
            or environment._source_fingerprint != self.saved["source_fingerprint"]
            or environment._template_name != self.saved["template_id"]
            or environment.actor_user != self.saved["actor_user"]
        ):
            raise ValueError("Regrade environment differs from the saved submission")
        await super().setup(environment)
        baseline = json.loads((self.logs_dir / "submission/baseline.json").read_text())
        if (
            hashlib.sha256(json.dumps(baseline, sort_keys=True).encode()).hexdigest()
            != self.saved["baseline_sha256"]
        ):
            raise ValueError("Fresh captured filesystem differs from the saved baseline")

    async def run(self, instruction, environment, context):
        await super().run(instruction, environment, context)
        fresh_path = self.logs_dir / "submission/manifest.json"
        fresh = self.validate_submission(fresh_path, digest(fresh_path))
        if any(
            fresh[key] != self.saved[key]
            for key in ("baseline_sha256", "changed", "removed", "archived_files")
        ):
            raise ValueError("Captured submission changed before regrading")
        record = {
            "method": self.method,
            "source_manifest": str(self.source_manifest),
            "source_sha256": self.source_sha256,
            "baseline_sha256": fresh["baseline_sha256"],
            "model_calls": 0,
        }
        context.metadata = record
        save_json(self.logs_dir / "regrade-provenance.json", record)


def file_submission(path, expected_sha):
    from harnesslab.coding.submission_restore import file_members

    manifest = checked_json(path, expected_sha)
    baseline = json.loads((path.parent / "baseline.json").read_text())
    if (
        hashlib.sha256(json.dumps(baseline, sort_keys=True).encode()).hexdigest()
        != manifest["baseline_sha256"]
    ):
        raise ValueError("Saved baseline changed")
    archive = path.parent / manifest["archive"]
    if digest(archive) != manifest["sha256"] or archive.stat().st_size != manifest["bytes"]:
        raise ValueError("Saved submission archive changed")
    file_members(manifest, archive)
    return manifest


class FileSubmissionRegrader(UnchangedSubmissionRegrader):
    validate_submission = staticmethod(file_submission)
    method = "restored-filesystem-submission"

    @staticmethod
    def name():
        return "harnesslab-file-submission-regrader"

    async def run(self, instruction, environment, context):
        from harnesslab.coding.native_environment import CONTROL

        remote_archive = CONTROL + "/saved-submission.tar.gz"
        await environment.upload_archive(
            self.source_manifest.parent / self.saved["archive"],
            self.saved["sha256"],
            remote_archive,
        )
        module = Path(__file__).with_name("submission_restore.py").read_text()
        # The sandbox helper is standalone; submission_delta.py is already installed there.
        module = module.replace("from harnesslab.coding.submission_delta", "from submission_delta")
        await environment._sandbox.files.write(CONTROL + "/submission_restore.py", module)
        await environment._sandbox.files.write(
            CONTROL + "/saved-manifest.json", json.dumps(self.saved)
        )
        code = f"""import json,sys
from pathlib import Path
sys.path.insert(0,{CONTROL!r})
from submission_restore import restore_file_delta
baseline=json.loads(Path({(CONTROL + "/baseline.json")!r}).read_text())
manifest=json.loads(Path({(CONTROL + "/saved-manifest.json")!r}).read_text())
print(json.dumps(restore_file_delta(Path('/'),baseline,manifest,Path({remote_archive!r}))))
"""
        result = await environment.python_command(code, timeout=300)
        save_json(self.logs_dir / "restore-result.json", json.loads(result.stdout))
        await super().run(instruction, environment, context)
