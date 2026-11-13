"""Cached installer transport preserves curl behavior and rejects changed bytes."""

import asyncio
import hashlib
import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from harnesslab.coding.verifier_cache import curl_wrapper, prepare_verifier


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


def test_verifier_preparation_initializes_upload_directory_and_cached_environment(
    tmp_path, monkeypatch
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
            prepare_tb21=bootstrap, verifier_environment=lambda: {"UV_PYTHON": "pinned-python"}
        ),
    )

    async def upload(path, sha, target):
        events.append((str(path), sha, target))

    async def command(text, timeout=120):
        events.append(text)
        return SimpleNamespace(stdout="/usr/bin/curl\n" if text == "command -v curl" else "")

    async def write(path, content):
        files[path] = content

    environment = SimpleNamespace(
        _root=tmp_path,
        upload_archive=upload,
        root_command=command,
        _startup_env=lambda: {"PATH": "/usr/bin"},
        _sandbox=SimpleNamespace(files=SimpleNamespace(write=write)),
    )
    spec = {
        "archives": [{"archive": "cache/public.tar.gz", "sha256": "pinned-sha"}],
        "install_command": "install-recorded-dependencies",
        "downloads": {},
        "env": {"UV_OFFLINE": "1"},
    }
    result = asyncio.run(prepare_verifier(environment, spec, "/controller", "python"))
    assert events[0] == "bootstrap"
    assert "install-recorded-dependencies" in events
    assert result == {
        "UV_PYTHON": "pinned-python",
        "UV_OFFLINE": "1",
        "PATH": "/controller/verifier-bin:/usr/bin",
    }
    assert json.loads(files["/controller/verifier-prerequisites.json"]) == spec
