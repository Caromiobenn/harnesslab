"""A saved delta reproduces edits, additions, removals and permissions against its baseline."""

import os
import shutil
import stat
import tarfile

import pytest

from harnesslab.coding.submission_delta import capture_delta, snapshot


def test_delta_reconstructs_changed_submission_without_recopying_inputs(tmp_path):
    original = tmp_path / "source"
    app = original / "app"
    app.mkdir(parents=True)
    (app / "dataset.bin").write_bytes(b"public-input" * 10000)
    (app / "solution.py").write_text("unfinished")
    (app / "remove.txt").write_text("remove me")
    replay = tmp_path / "replay"
    shutil.copytree(original, replay)
    baseline = snapshot(original, ["/app"])
    (app / "solution.py").write_text("print('answer')\n")
    (app / "solution.py").chmod(0o750)
    (app / "result.json").write_text('{"answer": 42}\n')
    (app / "remove.txt").unlink()
    archive = tmp_path / "submission.tar.gz"
    result = capture_delta(original, ["/app"], baseline, archive)
    assert "/app/dataset.bin" not in result["changed"]
    assert result["removed"] == ["/app/remove.txt"]
    assert not result["changed_during_capture"]
    for name in result["removed"]:
        (replay / name.lstrip("/")).unlink()
    with tarfile.open(archive) as saved:
        saved.extractall(replay, filter="fully_trusted")
    assert snapshot(replay, ["/app"]) == snapshot(original, ["/app"])
    assert stat.S_IMODE((replay / "app/solution.py").stat().st_mode) == 0o750


@pytest.mark.skipif(os.name == "nt", reason="Linux task symlink semantics")
def test_capture_records_link_identity_without_archiving_its_external_target(tmp_path):
    root = tmp_path / "root"
    (root / "app").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.write_text("outside selected paths")
    baseline = snapshot(root, ["/app"])
    (root / "app/link").symlink_to(outside)
    assert snapshot(root, ["/app/link/nested"]) == {
        "/app/link": snapshot(root, ["/app/link"])["/app/link"]
    }
    result = capture_delta(root, ["/app"], baseline, tmp_path / "saved.tar.gz")
    assert result["changed"]["/app/link"]["kind"] == "symlink"
    assert result["archived_files"] == {}
    with tarfile.open(tmp_path / "saved.tar.gz") as source:
        member = source.getmember("app/link")
        assert member.issym() and member.linkname == str(outside)


def test_missing_output_is_recorded_and_capture_cannot_include_itself(tmp_path):
    root = tmp_path / "root"
    (root / "app").mkdir(parents=True)
    baseline = snapshot(root, ["/app/output.txt"])
    result = capture_delta(root, ["/app/output.txt"], baseline, tmp_path / "saved.tar.gz")
    assert baseline == {"/app/output.txt": {"kind": "missing"}}
    assert result["changed"] == {} and result["archived_files"] == {}
    with pytest.raises(ValueError, match="outside"):
        capture_delta(root, ["/app"], baseline, root / "app/capture.tar.gz")
