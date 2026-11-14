import copy

import pytest

from harnesslab.coding.config import save_json
from harnesslab.coding.control_reuse import (
    check_prerequisites,
    load_control_reuse,
    save_reused_control,
    source_differences,
)
from harnesslab.coding.reuse import digest


@pytest.fixture
def control_fixture(tmp_path):
    inputs = {"tasks": {"task": {"capture_paths": ["/app"], "archives": []}}}
    source_inputs = tmp_path / "source-inputs.json"
    target_inputs = tmp_path / "target-inputs.json"
    save_json(source_inputs, inputs)
    save_json(target_inputs, inputs)
    configuration = {
        "benchmark": "terminal-bench-2.1",
        "revision": "pinned",
        "network_mode": "offline",
        "prerequisites_manifest": target_inputs.name,
        "reasoning_effort": "high",
        "langsmith_tracing": True,
    }
    task = {"task": "task", "path": "/new/task", "source_fingerprint": "image", "agent_seconds": 90}
    target = {
        "configuration": configuration,
        "tasks": [task],
        "source_hashes": {"runtime.py": "new", target_inputs.name: digest(target_inputs)},
    }
    outcomes = []
    for mode in ("offline", "public"):
        for group, reward in (("empty", 0), ("oracle", 1)):
            trial = tmp_path / "trials" / mode / group
            summary = {"tests": 3, "passed": 3 * reward, "failed": 3 * (1 - reward)}
            save_json(trial / "verifier/ctrf.json", {"results": {"summary": summary}})
            outcomes.append(
                {
                    "task": "task",
                    "network_mode": mode,
                    "group": group,
                    "repeat": 0,
                    "reward": reward,
                    "pipeline_ok": True,
                    "cleanup_verified": True,
                    "control_accepted": True,
                    "trial": str(trial),
                    "ctrf_summary": summary,
                }
            )
    source = {
        "model_calls": 0,
        "configuration": {**configuration, "langsmith_tracing": False},
        "tasks": [{**task, "path": "/old/task"}],
        "source_hashes": {"runtime.py": "old"},
        "manifest_sha256": digest(source_inputs),
        "outcomes": outcomes,
    }
    acceptance = tmp_path / "acceptance.json"
    save_json(acceptance, source)
    entry = {
        "task": "task",
        "acceptance_path": str(acceptance),
        "acceptance_sha256": digest(acceptance),
        "prerequisites_path": str(source_inputs),
        "reviewed_source_differences": source_differences(
            source["source_hashes"], target["source_hashes"]
        ),
        "compatibility_reason": "Identical task/cache bytes; reviewed cache extraction update.",
    }
    manifest = {
        "target_source_hashes": copy.deepcopy(target["source_hashes"]),
        "references": [entry],
    }
    path = tmp_path / "controls.json"
    save_json(path, manifest)
    return tmp_path, path, manifest, target, source


@pytest.mark.parametrize("mode", ["offline", "public"])
def test_only_matching_network_controls_are_reused_with_original_evidence(control_fixture, mode):
    root, path, _, target, source = control_fixture
    target["configuration"]["network_mode"] = mode
    controls = load_control_reuse(root, path, target)
    assert set(controls) == {(mode, "task", group, 0) for group in ("empty", "oracle")}
    for key, row in controls.items():
        original = next(
            item
            for item in source["outcomes"]
            if item["network_mode"] == mode and item["group"] == key[2]
        )
        assert all(row[name] == value for name, value in original.items())
        assert save_reused_control(root / "batch", "new", row, False) == row
        assert save_reused_control(root / "batch", "new", row, True) == row
        with pytest.raises(ValueError, match="needs --resume"):
            save_reused_control(root / "batch", "new", row, False)


@pytest.mark.parametrize(
    "change",
    [
        "score",
        "cleanup",
        "missing_tests",
        "changed_tests",
        "inputs",
        "task",
        "review",
        "benchmark",
        "duplicate",
        "source",
        "model_calls",
        "missing_cell",
    ],
)
def test_invalid_control_evidence_is_rejected(control_fixture, change):
    root, path, manifest, target, source = control_fixture
    entry = manifest["references"][0]
    row = source["outcomes"][0]
    if change == "score":
        row["reward"] = 1
    elif change == "cleanup":
        row["cleanup_verified"] = False
    elif change in ("missing_tests", "changed_tests"):
        from pathlib import Path

        ctrf = Path(row["trial"]) / "verifier/ctrf.json"
        if change == "missing_tests":
            ctrf.unlink()
        else:
            save_json(ctrf, {"results": {"summary": {"tests": 1, "failed": 1}}})
    elif change == "inputs":
        changed = root / entry["prerequisites_path"]
        save_json(changed, {"tasks": {"task": {"capture_paths": ["/different"]}}})
        source["manifest_sha256"] = digest(changed)
    elif change == "task":
        target["tasks"][0]["agent_seconds"] = 180
    elif change == "review":
        entry["reviewed_source_differences"] = {}
    elif change == "benchmark":
        source["configuration"]["revision"] = "different"
    elif change == "duplicate":
        manifest["references"].append(copy.deepcopy(entry))
    elif change == "source":
        target["source_hashes"]["runtime.py"] = "changed"
    elif change == "model_calls":
        source["model_calls"] = 1
    else:
        source["outcomes"].pop(0)
    from pathlib import Path

    acceptance = Path(entry["acceptance_path"])
    save_json(acceptance, source)
    entry["acceptance_sha256"] = digest(acceptance)
    if change == "duplicate":
        manifest["references"][1]["acceptance_sha256"] = digest(acceptance)
    save_json(path, manifest)
    with pytest.raises(ValueError):
        load_control_reuse(root, path, target)


def test_control_for_another_task_does_not_replace_any_selected_cell(control_fixture):
    root, path, _, target, _ = control_fixture
    target["tasks"] = []
    assert load_control_reuse(root, path, target) == {}


@pytest.mark.parametrize("change", [None, "archive", "runtime", "probe", "controls", "model"])
def test_python_amendment_only_reuses_unchanged_tasks_after_cloud_acceptance(
    control_fixture, change
):
    root, _, _, _, source = control_fixture
    before = {"archives": [{"sha256": "original"}], "capture_paths": ["/app"]}
    after = {**before, "actor_python_fallback": True}
    accepted = {
        "ok": True,
        "model_calls": 0,
        "runtime_sha256": "runtime",
        "probes": [
            {"mode": mode, "ok": True, "cleanup_verified": True} for mode in ("offline", "public")
        ],
        "controls": source["outcomes"],
    }
    if change == "archive":
        after["archives"] = [{"sha256": "changed"}]
    elif change == "runtime":
        accepted["runtime_sha256"] = "another-runtime"
    elif change == "probe":
        accepted["probes"][0]["ok"] = False
    elif change == "controls":
        accepted["controls"].pop()
    elif change == "model":
        accepted["model_calls"] = 1
    path = root / "python-acceptance.json"
    save_json(path, accepted)
    entry = {"actor_python_amendment": {"path": str(path), "sha256": digest(path)}}
    hashes = {"src/harnesslab/coding/native_environment.py": "runtime"}
    if change:
        with pytest.raises(ValueError):
            check_prerequisites(before, after, entry, hashes)
    else:
        check_prerequisites(before, after, entry, hashes)
