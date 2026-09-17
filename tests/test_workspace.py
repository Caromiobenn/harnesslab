from pathlib import Path

import pytest

from harnesslab.benchmark import load_benchmark_catalog
from harnesslab.workspace import (
    WorkspaceToolRegistry,
    apply_reference_files,
    materialize_workspace,
    snapshot_workspace,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CATALOG = PROJECT_ROOT / "benchmarks/catalog-v0.2.yaml"


def _file_case():
    return load_benchmark_catalog(CATALOG).cases[2]


def test_workspace_tools_enforce_root_permissions_and_budget(tmp_path: Path) -> None:
    workspace = materialize_workspace(_file_case(), tmp_path / "workspace")
    assert workspace is not None
    registry = WorkspaceToolRegistry(
        workspace,
        writable_paths=["/output"],
        max_calls=20,
    )

    assert registry.ls("/") == ["/input/", "/output/"]
    assert '"O-100"' in registry.read_file("/input/batch-a.json")
    assert registry.glob("/input/*.json") == [
        "/input/batch-a.json",
        "/input/batch-b.json",
    ]
    assert any("O-104" in match for match in registry.grep("O-104", "input/*.json"))
    assert "wrote" in registry.write_file("/output/result.txt", "alpha beta alpha")

    with pytest.raises(ValueError, match="not unique"):
        registry.edit_file("/output/result.txt", "alpha", "gamma")
    assert "2 occurrence" in registry.edit_file(
        "/output/result.txt",
        "alpha",
        "gamma",
        replace_all=True,
    )
    assert registry.read_file("/output/result.txt") == "gamma beta gamma"
    assert {tool.name for tool in registry.as_langchain_tools()} == {
        "ls",
        "read_file",
        "write_file",
        "edit_file",
        "glob",
        "grep",
    }

    with pytest.raises(PermissionError, match="read-only"):
        registry.write_file("/input/forbidden.txt", "no")
    with pytest.raises(ValueError, match="unsafe"):
        registry.read_file("/../outside.txt")
    with pytest.raises(FileNotFoundError):
        registry.read_file("/missing.txt")
    with pytest.raises(ValueError, match="not a directory"):
        registry.ls("/output/result.txt")

    limited = WorkspaceToolRegistry(workspace, writable_paths=["/output"], max_calls=1)
    limited.ls("/")
    with pytest.raises(RuntimeError, match="tool-call limit"):
        limited.ls("/")


def test_workspace_reference_and_snapshots_are_content_addressed(tmp_path: Path) -> None:
    case = _file_case()
    workspace = materialize_workspace(case, tmp_path / "workspace")
    assert workspace is not None
    initial = snapshot_workspace(workspace)

    apply_reference_files(workspace, case.evaluation.reference_submission)
    final = snapshot_workspace(workspace)

    assert "input/batch-a.json" in initial["files"]
    assert "output/summary.json" not in initial["files"]
    assert final["files"]["output/summary.json"]["size_bytes"] > 0
    assert (
        initial["files"]["input/batch-a.json"]["sha256"]
        == final["files"]["input/batch-a.json"]["sha256"]
    )

    with pytest.raises(ValueError, match="files mapping"):
        apply_reference_files(workspace, {"not_files": {}})
    with pytest.raises(ValueError, match="must be strings"):
        apply_reference_files(workspace, {"files": {"output/bad": 3}})

    (workspace / "output/link").symlink_to(workspace / "input/batch-a.json")
    with pytest.raises(ValueError, match="symlinks"):
        snapshot_workspace(workspace)


def test_structured_case_does_not_materialize_workspace(tmp_path: Path) -> None:
    case = load_benchmark_catalog(CATALOG).cases[0]

    assert materialize_workspace(case, tmp_path / "unused") is None
    assert not (tmp_path / "unused").exists()
