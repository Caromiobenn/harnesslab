import hashlib
import importlib.util
import io
import subprocess
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


@pytest.mark.parametrize("changed", [False, True])
def test_pinned_git_weights_and_original_download_alias_share_verified_bytes(
    builder, tmp_path, monkeypatch, changed
):
    data = b"public model weights"
    blob = b"blob " + str(len(data)).encode() + b"\0" + data
    monkeypatch.setattr(builder.urllib.request, "urlopen", lambda url, timeout: io.BytesIO(data))
    recipe = {
        "transport": "curl",
        "files": [
            {
                "name": "weights.pt",
                "url": "https://public/pinned/weights.pt",
                "aliases": ["https://public/master/weights.pt"],
                "git_blob_sha1": "wrong"
                if changed
                else hashlib.sha1(blob, usedforsecurity=False).hexdigest(),
            }
        ],
    }
    if changed:
        with pytest.raises(ValueError, match="pinned Git object"):
            builder.prepare_files(tmp_path, "fixture", recipe)
    else:
        _, downloads, files = builder.prepare_files(tmp_path, "fixture", recipe)
        assert (
            downloads["https://public/pinned/weights.pt"]
            == downloads["https://public/master/weights.pt"]
        )
        assert len(files) == 1 and files["weights.pt"]["sha256"] == hashlib.sha256(data).hexdigest()


def test_verifier_weights_can_be_read_from_a_pinned_git_cache_without_network(
    builder, tmp_path, monkeypatch
):
    source = tmp_path / "public.git"
    subprocess.run(["git", "init", "--bare", str(source)], check=True, capture_output=True)
    data = b"public weights from the fixed repository"

    def git(*args, input=None):
        return subprocess.check_output(
            ["git", "--git-dir", str(source), *args], input=input
        ).strip()

    blob = git("hash-object", "-w", "--stdin", input=data).decode()
    tree = git("mktree", input=f"100644 blob {blob}\tweights.pt\n".encode()).decode()
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Fixture")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "fixture@example.invalid")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Fixture")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "fixture@example.invalid")
    revision = git("commit-tree", tree, "-m", "public input").decode()
    archive = tmp_path / "public.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        output.add(source, arcname="opt/harnesslab-public-git/fixture.git")
    recipe = {
        "git_revision": revision,
        "files": [
            {
                "name": "weights.pt",
                "git_path": "weights.pt",
                "git_blob_sha1": blob,
                "url": "https://fixture/weights.pt",
            }
        ],
    }
    (tmp_path / "cache/tmp").mkdir(parents=True)
    cached = {"recipe": {"revision": revision}, "archive": {"archive": archive.name}}
    files = builder.git_input_files(tmp_path, "fixture", recipe, cached)
    assert files == {"weights.pt": data}

    def network_disabled(*args, **kwargs):
        raise AssertionError("A pinned Git input must not be downloaded again")

    monkeypatch.setattr(builder.urllib.request, "urlopen", network_disabled)
    _, downloads, _ = builder.prepare_files(tmp_path, "fixture", recipe, files)
    assert downloads["https://fixture/weights.pt"]["sha256"] == hashlib.sha256(data).hexdigest()


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
