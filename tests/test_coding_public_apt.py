import hashlib
import json
import subprocess
import sys

import pytest

from harnesslab.coding.public_apt import registration_wrapper, repository_inputs


def test_public_repository_registration_replays_bytes_and_preserves_apt_environment(tmp_path):
    source = tmp_path / "public.sources"
    source.write_text("Types: deb\nURIs: https://example.org\nSigned-By: public-test-key\n")
    recipe = {
        "source_file": source.name,
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "ppa": "ppa:test/example",
    }
    repositories = repository_inputs(tmp_path, [recipe])
    prefix = tmp_path / "cache"
    (prefix / "repositories").mkdir(parents=True)
    cached = prefix / "repositories" / source.name
    cached.write_bytes(source.read_bytes())
    apt = tmp_path / "apt"
    apt.write_text(
        f"#!{sys.executable}\nimport os,sys\nprint(os.environ['APT_CONFIG'])\n"
        "sys.exit(0 if sys.argv[1:]==['update'] else 9)\n"
    )
    apt.chmod(0o755)
    fallback = tmp_path / "fallback"
    fallback.write_text(
        f"#!{sys.executable}\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\nsys.exit(17)\n"
    )
    fallback.chmod(0o755)
    wrapper = tmp_path / "add-apt-repository"
    destination = tmp_path / "sources"
    wrapper.write_text(
        registration_wrapper(
            sys.executable, str(prefix), repositories, str(fallback), str(destination), str(apt)
        )
    )
    result = subprocess.run(
        [sys.executable, str(wrapper), "-y", recipe["ppa"]],
        env={"APT_CONFIG": "pinned-offline.conf"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "pinned-offline.conf" in result.stdout
    assert (destination / source.name).read_bytes() == source.read_bytes()
    assert json.loads((prefix / "repository-hits.jsonl").read_text())["sha256"] == recipe["sha256"]
    # Unsupported options retain the real command's arguments and exit status.
    result = subprocess.run(
        [sys.executable, str(wrapper), "--remove", recipe["ppa"]], capture_output=True, text=True
    )
    assert result.returncode == 17
    assert json.loads(result.stdout) == ["--remove", recipe["ppa"]]
    cached.write_text("changed")
    result = subprocess.run(
        [sys.executable, str(wrapper), "-y", recipe["ppa"]], capture_output=True, text=True
    )
    assert result.returncode != 0 and "metadata changed" in result.stderr
    assert (destination / source.name).read_bytes() == source.read_bytes()


def test_public_repository_recipe_rejects_changed_or_unsigned_input(tmp_path):
    source = tmp_path / "public.sources"
    source.write_text("Types: deb\n")
    recipe = {"source_file": source.name, "sha256": "0" * 64, "ppa": "ppa:test/example"}
    with pytest.raises(ValueError, match="checksum"):
        repository_inputs(tmp_path, [recipe])
    recipe["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="signed Deb822"):
        repository_inputs(tmp_path, [recipe])
