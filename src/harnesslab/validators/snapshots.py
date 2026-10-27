"""Evaluator-only scoring of frozen candidates after runtime execution ends."""

from __future__ import annotations

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from harnesslab.benchmark import BenchmarkCase
from harnesslab.validators.benchmark import evaluate_benchmark_submission
from harnesslab.workspace import materialize_workspace


def evaluate_candidate_snapshots(
    case: BenchmarkCase, candidates: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    results = []
    for candidate in candidates:
        with TemporaryDirectory(prefix="harnesslab-retrospective-") as temporary:
            workspace = materialize_workspace(case, Path(temporary) / "workspace")
            if workspace is not None:
                for relative, content in candidate.get("files", {}).items():
                    target = (workspace / relative).resolve()
                    if not target.is_relative_to(workspace.resolve()):
                        raise ValueError("candidate snapshot escapes workspace")
                    if not any(
                        relative == allowed.strip("/")
                        or relative.startswith(allowed.strip("/") + "/")
                        for allowed in case.public.environment.writable_paths
                    ):
                        raise ValueError("candidate snapshot contains a non-output path")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(content, encoding="utf-8")
            verdict = evaluate_benchmark_submission(case, candidate["output"], workspace=workspace)
            integrity_ok = True
            if case.workspace_fixture is not None:
                original = {
                    path: {
                        "sha256": hashlib.sha256(content.encode()).hexdigest(),
                        "size_bytes": len(content.encode()),
                    }
                    for path, content in case.workspace_fixture.files.items()
                    if path.startswith("input/")
                }
                observed = candidate.get("workspace_snapshot", {}).get("files", {})
                integrity_ok = original == {
                    k: v for k, v in observed.items() if k.startswith("input/")
                }
            results.append(
                {
                    "candidate_id": candidate["candidate_id"],
                    "passed": verdict.passed and integrity_ok,
                    "input_integrity": integrity_ok,
                }
            )
    return results
