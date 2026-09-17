"""Per-run workspace materialization, safe tools, and auditable snapshots."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
from threading import Lock
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool

from harnesslab.benchmark import BenchmarkCase


def materialize_workspace(case: BenchmarkCase, directory: Path) -> Path | None:
    """Create a fresh workspace from a public fixture, or return None when unused."""
    if case.public.environment.workspace == "none":
        return None
    directory.mkdir(parents=True, exist_ok=False)
    fixture = case.workspace_fixture
    if fixture is not None:
        for relative_directory in fixture.directories:
            _fixture_target(directory, relative_directory).mkdir(parents=True, exist_ok=True)
        for relative_path, content in fixture.files.items():
            target = _fixture_target(directory, relative_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
    _make_input_read_only(directory / "input")
    return directory


def snapshot_workspace(directory: Path) -> dict[str, Any]:
    """Hash every regular file without copying potentially sensitive contents."""
    files: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"workspace symlinks are not allowed: {path}")
        if path.is_file():
            relative = path.relative_to(directory).as_posix()
            data = path.read_bytes()
            files[relative] = {
                "sha256": hashlib.sha256(data).hexdigest(),
                "size_bytes": len(data),
            }
    return {"files": files}


def apply_reference_files(workspace: Path, reference_submission: Any) -> None:
    """Materialize evaluator-only reference files for benchmark self-verification."""
    if not isinstance(reference_submission, dict) or not isinstance(
        reference_submission.get("files"), dict
    ):
        raise ValueError("file-mode reference_submission must contain a files mapping")
    for relative_path, content in reference_submission["files"].items():
        if not isinstance(relative_path, str) or not isinstance(content, str):
            raise ValueError("reference file paths and contents must be strings")
        target = _fixture_target(workspace, relative_path.lstrip("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


class WorkspaceToolRegistry:
    """Expose bounded text-file operations rooted inside one run workspace."""

    def __init__(
        self,
        root: Path,
        *,
        writable_paths: list[str],
        max_calls: int,
        max_file_size_bytes: int = 1_000_000,
    ) -> None:
        self.root = root.resolve()
        self.writable_roots = tuple(
            self._resolve(path, require_exists=False) for path in writable_paths
        )
        self.max_calls = max_calls
        self.max_file_size_bytes = max_file_size_bytes
        self.call_count = 0
        self._lock = Lock()

    def as_langchain_tools(self) -> list[BaseTool]:
        return [
            StructuredTool.from_function(
                func=self.ls,
                name="ls",
                description="List files and directories under a virtual workspace path.",
            ),
            StructuredTool.from_function(
                func=self.read_file,
                name="read_file",
                description="Read a UTF-8 text file from the isolated workspace.",
            ),
            StructuredTool.from_function(
                func=self.write_file,
                name="write_file",
                description="Write a UTF-8 text file under an allowed writable path.",
            ),
            StructuredTool.from_function(
                func=self.edit_file,
                name="edit_file",
                description="Replace exact text in an existing writable UTF-8 file.",
            ),
            StructuredTool.from_function(
                func=self.glob,
                name="glob",
                description="Find workspace files matching a relative glob pattern.",
            ),
            StructuredTool.from_function(
                func=self.grep,
                name="grep",
                description="Find literal text in UTF-8 workspace files.",
            ),
        ]

    def ls(self, path: str = "/") -> list[str]:
        """List the immediate children of a workspace directory."""
        self._consume_call()
        target = self._resolve(path)
        if not target.is_dir():
            raise ValueError(f"not a directory: {path}")
        return [
            f"/{child.relative_to(self.root).as_posix()}{'/' if child.is_dir() else ''}"
            for child in sorted(target.iterdir())
        ]

    def read_file(self, path: str) -> str:
        """Read one UTF-8 file."""
        self._consume_call()
        target = self._resolve(path)
        if not target.is_file():
            raise ValueError(f"not a file: {path}")
        if target.stat().st_size > self.max_file_size_bytes:
            raise ValueError(f"file exceeds {self.max_file_size_bytes} bytes: {path}")
        return target.read_text(encoding="utf-8")

    def write_file(self, path: str, content: str) -> str:
        """Create or replace one UTF-8 file."""
        self._consume_call()
        target = self._resolve(path, require_exists=False)
        self._require_writable(target)
        encoded = content.encode()
        if len(encoded) > self.max_file_size_bytes:
            raise ValueError(f"content exceeds {self.max_file_size_bytes} bytes")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(encoded)
        return f"wrote {len(encoded)} bytes to /{target.relative_to(self.root).as_posix()}"

    def edit_file(
        self,
        path: str,
        old_text: str,
        new_text: str,
        replace_all: bool = False,
    ) -> str:
        """Replace an exact text fragment in a writable file."""
        self._consume_call()
        target = self._resolve(path)
        self._require_writable(target)
        content = target.read_text(encoding="utf-8")
        occurrences = content.count(old_text)
        if occurrences == 0:
            raise ValueError("old_text was not found")
        if occurrences > 1 and not replace_all:
            raise ValueError("old_text is not unique; set replace_all=true to replace every match")
        updated = content.replace(old_text, new_text, -1 if replace_all else 1)
        if len(updated.encode()) > self.max_file_size_bytes:
            raise ValueError(f"edited content exceeds {self.max_file_size_bytes} bytes")
        target.write_text(updated, encoding="utf-8")
        return f"replaced {occurrences if replace_all else 1} occurrence(s)"

    def glob(self, pattern: str) -> list[str]:
        """Return files matching one safe relative glob."""
        self._consume_call()
        safe_pattern = pattern.lstrip("/")
        _validate_relative_parts(safe_pattern)
        return [
            f"/{path.relative_to(self.root).as_posix()}"
            for path in sorted(self.root.glob(safe_pattern))
            if path.is_file() and not path.is_symlink()
        ]

    def grep(self, query: str, pattern: str = "**/*") -> list[str]:
        """Return path:line-number:text matches for a literal query."""
        self._consume_call()
        safe_pattern = pattern.lstrip("/")
        _validate_relative_parts(safe_pattern)
        matches: list[str] = []
        for path in sorted(self.root.glob(safe_pattern)):
            if not path.is_file() or path.is_symlink():
                continue
            if path.stat().st_size > self.max_file_size_bytes:
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                continue
            relative = path.relative_to(self.root).as_posix()
            matches.extend(
                f"/{relative}:{line_number}:{line}"
                for line_number, line in enumerate(lines, start=1)
                if query in line
            )
        return matches[:1000]

    def _resolve(self, virtual_path: str, *, require_exists: bool = True) -> Path:
        normalized = virtual_path.replace("\\", "/")
        relative = normalized.lstrip("/")
        _validate_relative_parts(relative)
        target = (self.root / relative).resolve()
        if not target.is_relative_to(self.root):
            raise ValueError(f"path escapes workspace: {virtual_path}")
        if require_exists and not target.exists():
            raise FileNotFoundError(f"workspace path does not exist: {virtual_path}")
        return target

    def _require_writable(self, target: Path) -> None:
        if not any(target == root or target.is_relative_to(root) for root in self.writable_roots):
            allowed = [f"/{path.relative_to(self.root).as_posix()}" for path in self.writable_roots]
            raise PermissionError(f"path is read-only: {target}; writable roots: {allowed}")

    def _consume_call(self) -> None:
        with self._lock:
            self.call_count += 1
            if self.call_count > self.max_calls:
                raise RuntimeError(f"domain tool-call limit exceeded: {self.max_calls}")


def _fixture_target(root: Path, relative_path: str) -> Path:
    _validate_relative_parts(relative_path)
    target = (root / relative_path).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError(f"fixture path escapes workspace: {relative_path}")
    return target


def _validate_relative_parts(path: str) -> None:
    parts = PurePosixPath(path).parts
    if ".." in parts or "~" in parts:
        raise ValueError(f"unsafe workspace path: {path!r}")


def _make_input_read_only(input_directory: Path) -> None:
    if not input_directory.exists():
        return
    for path in sorted(input_directory.rglob("*"), reverse=True):
        path.chmod(0o755 if path.is_dir() else 0o444)
    input_directory.chmod(0o755)
