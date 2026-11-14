import importlib.util
from pathlib import Path

import pytest


def planner():
    path = Path(__file__).resolve().parents[1] / "scripts/prepare_coding_python_continuation.py"
    spec = importlib.util.spec_from_file_location("python_continuation", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_continuation_keeps_only_requested_unstarted_groups(tmp_path):
    old = {
        "units": [
            {"task": "a", "network": "offline", "groups": ["mini"], "batch": "started"},
            {
                "task": "a",
                "network": "public",
                "groups": ["mini", "rubric_evidence"],
                "batch": "new",
            },
        ]
    }
    (tmp_path / "artifacts/coding/started").mkdir(parents=True)
    assert planner().replacement_units([(tmp_path, old, [1])]) == [(tmp_path, old["units"][1])]
    with pytest.raises(ValueError, match="execution directory"):
        planner().replacement_units([(tmp_path, old, [0])])


def test_continuation_rejects_duplicate_cells_across_roots(tmp_path):
    unit = {"task": "a", "network": "public", "groups": ["mini"], "batch": "not-started"}
    with pytest.raises(ValueError, match="overlap"):
        planner().replacement_units(
            [
                (tmp_path / "a", {"units": [unit]}, [0]),
                (tmp_path / "b", {"units": [unit]}, [0]),
            ]
        )
