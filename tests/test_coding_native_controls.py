"""Control acceptance requires real assertions and matching cache provenance."""

import hashlib
import json

import pytest

from harnesslab.coding.native_controls import (
    official_control_result,
    public_cache,
    task_prerequisites,
)


def cache_origin(tmp_path, name, **fields):
    root = tmp_path / name
    root.mkdir()
    archive = root / (name + ".tar.gz")
    archive.write_bytes(b"recorded public package bytes")
    record = {
        "ok": True,
        "cleanup": {"verified": True},
        "model_calls": 0,
        "archive": {
            "archive": archive.name,
            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "bytes": archive.stat().st_size,
        },
        **fields,
    }
    receipt = root / "receipt.json"
    receipt.write_text(json.dumps(record))
    return {
        "root": str(root),
        "receipt": receipt.name,
        "receipt_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
        "archive": record["archive"],
        "tasks": ["task"],
    }


def test_public_cache_checks_receipt_archive_and_preparation(tmp_path):
    destination = tmp_path / "destination"
    origin = cache_origin(tmp_path, "public")
    saved = public_cache(destination, origin)
    assert (destination / "public.tar.gz").read_bytes() == b"recorded public package bytes"
    assert public_cache(destination, origin) == saved
    archive = destination / "public.tar.gz"
    archive.write_bytes(b"changed public bytes")
    with pytest.raises(ValueError, match="archive changed"):
        public_cache(destination, origin)
    receipt = tmp_path / "public/receipt.json"
    receipt.write_text("{}")
    with pytest.raises(ValueError, match="receipt changed"):
        public_cache(destination, origin)
    invalid = cache_origin(tmp_path, "unclean", cleanup={"verified": False})
    with pytest.raises(ValueError, match="did not pass"):
        public_cache(destination, invalid)


@pytest.mark.parametrize("custom", [False, True])
def test_task_profile_joins_only_matching_public_prerequisites(tmp_path, custom):
    task = tmp_path / "task"
    (task / "tests").mkdir(parents=True)
    (task / "tests/test.sh").write_text("official assertions")
    sha = hashlib.sha256((task / "tests/test.sh").read_bytes()).hexdigest()
    recipe = (
        {"test_script_sha256": sha, "source_fingerprint": "image"}
        if custom
        else {"recipe": {"test_script_sha256": {"task": sha}}}
    )
    python = cache_origin(tmp_path, "python", downloads={}, env={"UV_OFFLINE": "1"}, **recipe)
    system = cache_origin(tmp_path, "system", source_fingerprint="image", install_command="apt")
    families = {
        "shared_python": {} if custom else {"recipe": python},
        "custom_python": {"task": python} if custom else {},
        "system": {"task": system},
    }
    ledger = {"families": families}
    if custom:
        families["actor_python"] = {
            "task": cache_origin(
                tmp_path,
                "actor",
                source_fingerprint="image",
                env={"PIP_FIND_LINKS": "/public-wheels"},
            )
        }
    row = {"task": "task", "path": str(task), "source_fingerprint": "image"}
    profile = task_prerequisites(tmp_path / "runtime", row, ["/app", "/etc/nginx"], ledger)
    assert len(profile["archives"]) == int(custom)
    assert "install_command" not in profile
    if custom:
        assert profile["env"] == {"PIP_FIND_LINKS": "/public-wheels"}
    assert len(profile["verifier"]["archives"]) == 2
    assert profile["capture_paths"] == ["/app", "/etc/nginx"]
    assert profile["verifier"]["test_script_sha256"] == sha
    with pytest.raises(ValueError, match="official task image"):
        task_prerequisites(
            tmp_path / "runtime", {**row, "source_fingerprint": "other"}, ["/app"], ledger
        )
    (task / "tests/test.sh").write_text("changed assertions")
    with pytest.raises(ValueError, match="official test script"):
        task_prerequisites(tmp_path / "runtime", row, ["/app"], ledger)


def test_zero_reward_without_executed_tests_is_not_an_accepted_empty_control(tmp_path):
    outcome = {"trial": str(tmp_path), "pipeline_ok": True, "reward": 0, "cleanup_verified": True}
    assert not official_control_result(outcome, 0)["control_accepted"]
    (tmp_path / "verifier").mkdir()
    ctrf = tmp_path / "verifier/ctrf.json"
    ctrf.write_text(json.dumps({"results": {"summary": {"tests": 0}}}))
    assert not official_control_result(outcome, 0)["control_accepted"]
    ctrf.write_text(json.dumps({"results": {"summary": {"tests": 6, "passed": 0, "failed": 6}}}))
    assert official_control_result(outcome, 0)["control_accepted"]
    assert not official_control_result(outcome, 1)["control_accepted"]
    assert not official_control_result({**outcome, "cleanup_verified": False}, 0)[
        "control_accepted"
    ]
