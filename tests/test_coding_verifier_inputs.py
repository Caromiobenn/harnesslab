import hashlib
import importlib.util
import io
import tarfile
import zipfile
from pathlib import Path

import pytest


@pytest.fixture
def builder():
    path = Path(__file__).parents[1] / "scripts/prepare_coding_verifier_inputs.py"
    spec = importlib.util.spec_from_file_location("verifier_inputs", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_multiple_public_files_are_checksum_pinned_and_only_verifier_visible(
    builder, tmp_path, monkeypatch
):
    data = {
        "https://fixture/images.gz": b"public images",
        "https://fixture/labels.gz": b"public labels",
    }
    monkeypatch.setattr(
        builder.urllib.request, "urlopen", lambda url, timeout: io.BytesIO(data[url])
    )
    recipe = {
        "files": [
            {
                "name": url.rsplit("/", 1)[-1],
                "url": url,
                "md5": hashlib.md5(content, usedforsecurity=False).hexdigest(),
            }
            for url, content in data.items()
        ]
    }
    archive, downloads, files = builder.prepare_files(tmp_path, "fixture", recipe)
    assert set(downloads) == set(data)
    with tarfile.open(archive) as saved:
        assert len(saved.getmembers()) == 2
        for url, content in data.items():
            target = downloads[url]["path"]
            assert target.startswith("/opt/harnesslab-verifier-inputs/fixture/")
            assert saved.extractfile(target.lstrip("/")).read() == content
            assert downloads[url]["sha256"] == hashlib.sha256(content).hexdigest()
    assert sum(row["bytes"] for row in files.values()) == sum(map(len, data.values()))


def test_public_dataset_checksum_mismatch_stops_preparation(builder, tmp_path, monkeypatch):
    monkeypatch.setattr(
        builder.urllib.request, "urlopen", lambda url, timeout: io.BytesIO(b"changed")
    )
    with pytest.raises(ValueError, match="upstream dataset checksum"):
        builder.prepare_files(
            tmp_path, "fixture", {"files": [{"name": "input.gz", "url": "fixture", "md5": "wrong"}]}
        )
    assert not (tmp_path / "verifier-inputs.tar.gz").exists()


@pytest.mark.parametrize("changed_revision", [False, True])
def test_existing_zip_input_still_checks_the_original_commit(
    builder, tmp_path, monkeypatch, changed_revision
):
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as archive:
        archive.comment = b"changed" if changed_revision else b"fixed-commit"
        archive.writestr("testbed-master/data.txt", "public data")
    monkeypatch.setattr(
        builder.urllib.request, "urlopen", lambda url, timeout: io.BytesIO(content.getvalue())
    )
    recipe = {
        "url": "https://fixture/testbed.zip",
        "revision": "fixed-commit",
        "zip_root": "testbed-master",
    }
    if changed_revision:
        with pytest.raises(ValueError, match="different commit"):
            builder.prepare_files(tmp_path, "fixture", recipe)
    else:
        archive, downloads, _ = builder.prepare_files(tmp_path, "fixture", recipe)
        assert archive.exists() and downloads[recipe["url"]]["path"].endswith("/testbed.zip")
