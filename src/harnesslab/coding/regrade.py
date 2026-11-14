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
    @staticmethod
    def name():
        return "harnesslab-unchanged-submission-regrader"

    def __init__(self, *args, source_manifest, source_sha256, **kwargs):
        super().__init__(*args, **kwargs)
        self.source_manifest = Path(source_manifest)
        self.source_sha256 = source_sha256

    async def setup(self, environment):
        self.saved = unchanged_submission(self.source_manifest, self.source_sha256)
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
        fresh = unchanged_submission(fresh_path, digest(fresh_path))
        if fresh["baseline_sha256"] != self.saved["baseline_sha256"]:
            raise ValueError("Captured submission changed before regrading")
        record = {
            "method": "unchanged-filesystem-submission",
            "source_manifest": str(self.source_manifest),
            "source_sha256": self.source_sha256,
            "baseline_sha256": fresh["baseline_sha256"],
            "model_calls": 0,
        }
        context.metadata = record
        save_json(self.logs_dir / "regrade-provenance.json", record)
