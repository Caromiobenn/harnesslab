"""Cached installer transport preserves curl behavior and rejects changed bytes."""

import asyncio
import hashlib
import json
import os
import subprocess
import sys
import tarfile
from types import SimpleNamespace

import pytest

from harnesslab.coding.verifier_cache import (
    archive_extract_code,
    curl_wrapper,
    prepare_verifier,
    urllib_cache_hook,
)


@pytest.mark.skipif(os.name == "nt", reason="The cloud archive uses POSIX links and modes")
def test_public_archive_preserves_package_links_and_executable_modes(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    executable = source / "tool"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    os.link(executable, source / "hardlink")
    (source / "symlink").symlink_to("tool")
    archive = tmp_path / "public.tar.gz"
    with tarfile.open(archive, "w:gz") as stream:
        stream.add(source, arcname="package")
    target = tmp_path / "destination"
    result = subprocess.run(
        [sys.executable, "-c", archive_extract_code(str(archive), str(target))],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    unpacked = target / "package"
    assert (unpacked / "tool").read_bytes() == executable.read_bytes()
    assert (unpacked / "tool").stat().st_mode & 0o777 == 0o755
    assert (unpacked / "hardlink").stat().st_ino == (unpacked / "tool").stat().st_ino
    assert (unpacked / "symlink").is_symlink()
    assert (unpacked / "symlink").resolve() == unpacked / "tool"


@pytest.mark.skipif(os.name == "nt", reason="The cloud command launcher runs on Linux")
def test_cached_curl_preserves_options_output_and_unknown_urls(tmp_path):
    artifact = tmp_path / "public installer.sh"
    artifact.write_text("public installer")
    real = tmp_path / "real-curl"
    real.write_text(f"#!{sys.executable}\nimport json,sys;print(json.dumps(sys.argv[1:]))\n")
    real.chmod(0o755)
    log = tmp_path / "requests.jsonl"
    wrapper = tmp_path / "curl"
    url = "https://astral.sh/uv/0.9.5/install.sh"
    wrapper.write_text(
        curl_wrapper(
            sys.executable,
            str(real),
            {
                url: {
                    "path": str(artifact),
                    "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                }
            },
            str(log),
        )
    )
    wrapper.chmod(0o755)
    result = subprocess.run(
        [str(wrapper), "-LsSf", "-o", "output.sh", url], capture_output=True, text=True
    )
    assert result.returncode == 0
    assert json.loads(result.stdout) == ["-LsSf", "-o", "output.sh", artifact.as_uri()]
    assert json.loads(log.read_text())["url"] == url
    unknown = "http://localhost:8080/simple/vectorops/"
    result = subprocess.run([str(wrapper), "-f", unknown], capture_output=True, text=True)
    assert json.loads(result.stdout) == ["-f", unknown]
    assert len(log.read_text().splitlines()) == 1
    artifact.write_text("changed bytes")
    result = subprocess.run([str(wrapper), url], capture_output=True, text=True)
    assert result.returncode != 0
    assert "checksum mismatch" in result.stderr


@pytest.mark.parametrize("python_downloads", [False, True])
def test_verifier_preparation_initializes_upload_directory_and_cached_environment(
    tmp_path, monkeypatch, python_downloads
):
    events = []
    files = {}

    async def bootstrap(root, environment):
        assert (root / "cache/tmp").is_dir()
        events.append("bootstrap")

    monkeypatch.setitem(
        sys.modules,
        "benchmark_next_bootstrap",
        SimpleNamespace(
            DIRECTORY="/pinned-bootstrap",
            prepare_tb21=bootstrap,
            verifier_environment=lambda: {"UV_PYTHON": "pinned-python"},
        ),
    )

    async def upload(path, sha, target):
        events.append((str(path), sha, target))

    async def command(text, timeout=120):
        events.append(text)
        output = {
            "command -v curl": "/usr/bin/curl\n",
            "printf '%s' \"$PATH\"": "/image/bin:/usr/bin",
        }
        return SimpleNamespace(stdout=output.get(text, ""))

    async def write(path, content):
        files[path] = content

    environment = SimpleNamespace(
        _root=tmp_path,
        upload_archive=upload,
        root_command=command,
        python_command=command,
        _startup_env=lambda: {},
        _sandbox=SimpleNamespace(files=SimpleNamespace(write=write)),
    )
    spec = {
        "archives": [{"archive": "cache/public.tar.gz", "sha256": "pinned-sha"}],
        "install_command": "install-recorded-dependencies",
        "downloads": {},
        "env": {"UV_OFFLINE": "1"},
    }
    if python_downloads:
        spec["python_downloads"] = {
            "https://example.test/input.zip": {"path": "/public.zip", "sha256": "fixed"}
        }
        spec["env"]["PYTHONPATH"] = "/existing-helper"
    result = asyncio.run(prepare_verifier(environment, spec, "/controller", "python"))
    assert events[0] == "bootstrap"
    assert "install-recorded-dependencies" in events
    expected = {
        "UV_PYTHON": "pinned-python",
        "UV_OFFLINE": "1",
        "PATH": "/controller/verifier-bin:/pinned-bootstrap/uv-x86_64-unknown-linux-gnu:"
        "/image/bin:/usr/bin:/pinned-bootstrap/python313/bin",
    }
    if python_downloads:
        expected["PYTHONPATH"] = "/controller/verifier-python:/existing-helper"
        assert "urlopen" in files["/controller/verifier-python/sitecustomize.py"]
    assert result == expected
    assert json.loads(files["/controller/verifier-prerequisites.json"]) == spec


def test_urllib_verifier_cache_uses_exact_url_and_checks_bytes_in_real_python(tmp_path):
    archive = tmp_path / "testbed.zip"
    archive.write_bytes(b"public test archive")
    url = "https://cache-test.invalid/official.zip"
    log = tmp_path / "downloads.jsonl"
    (tmp_path / "sitecustomize.py").write_text(
        urllib_cache_hook(
            {
                url: {
                    "path": str(archive),
                    "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                }
            },
            str(log),
        )
    )
    code = f"""import urllib.request
urllib.request.urlretrieve({url!r},'copied.zip')
request=urllib.request.Request({url!r},headers={{'Method':'HEAD'}})
with urllib.request.urlopen(request) as response:
    assert response.length==len(b'public test archive') and response.url=={url!r}
assert urllib.request.urlopen({archive.as_uri()!r}).read()==b'public test archive'
"""
    env = {**os.environ, "PYTHONPATH": str(tmp_path)}
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=tmp_path, env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "copied.zip").read_bytes() == archive.read_bytes()
    assert len(log.read_text().splitlines()) == 2
    archive.write_bytes(b"changed archive")
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=tmp_path, env=env, capture_output=True, text=True
    )
    assert result.returncode != 0 and "checksum mismatch" in result.stderr
