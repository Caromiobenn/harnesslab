"""Persistence for immutable experiment manifests and append-only run artifacts."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


class ArtifactStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=False)

    def write_json(self, filename: str, value: Any) -> Path:
        path = self.directory / filename
        with path.open("x", encoding="utf-8") as handle:
            json.dump(_jsonable(value), handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        return path

    def append_jsonl(self, filename: str, values: Iterable[Any]) -> Path:
        path = self.directory / filename
        with path.open("a", encoding="utf-8") as handle:
            for value in values:
                line = json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True)
                handle.write(f"{line}\n")
        return path
