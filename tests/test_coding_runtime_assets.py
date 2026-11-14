import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


def importer():
    path = Path(__file__).parents[1] / "scripts/import_hongkong_infra.py"
    spec = importlib.util.spec_from_file_location("infra_asset_importer", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixtures(source):
    files = {
        "configs/benchmark-agent-runtime.json": b'{"python_artifact":"fixed-python.tar.gz"}',
        "scripts/benchmark_http_cache.py": b"public proxy source",
        "cache/public-data.tar.gz": b"publisher data",
        "scripts/benchmark_loopback_redirect.c": b"loopback source",
        "cache/loopback.so": b"verified binary",
    }
    for name, content in files.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    hashes = {name: hashlib.sha256(content).hexdigest() for name, content in files.items()}
    runtime = {
        "environments": {
            "data-task": {
                "http_cache": {
                    "path": "cache/public-data.tar.gz",
                    "sha256": hashes["cache/public-data.tar.gz"],
                    "helper_sha256": hashes["scripts/benchmark_http_cache.py"],
                }
            },
            "service-task": {
                "loopback_port_redirect": {
                    "artifact": {
                        "path": "cache/loopback.so",
                        "sha256": hashes["cache/loopback.so"],
                        "source_sha256": hashes["scripts/benchmark_loopback_redirect.c"],
                    }
                }
            },
        }
    }
    (source / "configs/benchmark-runtime-next.json").write_text(json.dumps(runtime))
    return files, hashes


def test_imports_declared_public_inputs_and_runtime_helper_dependencies(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    files, hashes = fixtures(source)
    module = importer()
    assert {"benchmark_next_http_cache.py", "benchmark_next_agent_runtime.py"} <= set(
        module.MODULES
    )
    assert module.import_runtime_assets(source, target) == hashes
    assert {name: (target / name).read_bytes() for name in files} == files


def test_changed_public_cache_is_rejected_before_copy(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    fixtures(source)
    (source / "cache/public-data.tar.gz").write_bytes(b"changed data")
    with pytest.raises(ValueError, match="checksum mismatch"):
        importer().import_runtime_assets(source, target)
    assert not (target / "cache/public-data.tar.gz").exists()
