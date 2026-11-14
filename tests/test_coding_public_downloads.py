import hashlib
import json
import shutil
import subprocess
import sys

from harnesslab.coding.public_downloads import wget_wrapper
from harnesslab.coding.verifier_cache import curl_wrapper


def fixture(tmp_path):
    data = b"public source archive"
    source = tmp_path / "source.tar.xz"
    source.write_bytes(data)
    url = "https://public.example/package.tar.xz"
    script = tmp_path / "wget.py"
    log = tmp_path / "hits.jsonl"
    script.write_text(
        wget_wrapper(
            sys.executable,
            sys.executable,
            {url: {"path": str(source), "sha256": hashlib.sha256(data).hexdigest()}},
            str(log),
        )
    )
    return data, source, url, script, log


def test_cached_wget_preserves_existing_default_filename(tmp_path):
    data, _, url, script, log = fixture(tmp_path)
    target = tmp_path / "package.tar.xz"
    target.write_bytes(b"existing")
    subprocess.run([sys.executable, str(script), url], cwd=tmp_path, check=True)
    assert target.read_bytes() == b"existing"
    assert target.with_name(target.name + ".1").read_bytes() == data
    assert json.loads(log.read_text())["url"] == url


def test_cached_wget_supports_explicit_stdout_and_rejects_changed_bytes(tmp_path):
    data, source, url, script, _ = fixture(tmp_path)
    result = subprocess.run(
        [sys.executable, str(script), "-q", "-O", "-", url], capture_output=True
    )
    assert result.returncode == 0 and result.stdout == data
    source.write_bytes(b"changed")
    result = subprocess.run(
        [sys.executable, str(script), "-O", str(tmp_path / "output"), url], capture_output=True
    )
    assert result.returncode != 0 and b"checksum mismatch" in result.stderr
    assert not (tmp_path / "output").exists()


def test_unsupported_wget_arguments_are_forwarded_to_original_command(tmp_path):
    _, _, _, script, log = fixture(tmp_path)
    result = subprocess.run(
        [sys.executable, str(script), "-c", 'print("original command")'],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0 and result.stdout.strip() == "original command"
    assert not log.exists()


def test_makefile_curl_download_works_with_http_protocols_disabled(tmp_path):
    real_curl = shutil.which("curl")
    assert real_curl, "The dependency preparation environment requires curl"
    artifact = tmp_path / "release.tar.gz"
    artifact.write_bytes(b"\x1f\x8bpublic release bytes\x00\xff")
    url = "https://github.com/upstream/package/archive/v1.0.tar.gz"
    wrapper = tmp_path / "curl.py"
    wrapper.write_text(
        curl_wrapper(
            sys.executable,
            real_curl,
            {
                url: {
                    "path": str(artifact),
                    "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                }
            },
            str(tmp_path / "hits.jsonl"),
        )
    )
    output = tmp_path / "download.tar.gz"
    result = subprocess.run(
        [
            sys.executable,
            str(wrapper),
            "--proto",
            "=file",
            "--silent",
            "--location",
            url,
            "-o",
            str(output),
            "--retry",
            "5",
            "--fail",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert output.read_bytes() == artifact.read_bytes()
