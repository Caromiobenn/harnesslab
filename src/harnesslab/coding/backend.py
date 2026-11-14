"""Deep Agents filesystem tools execute exclusively through the Harbor sandbox."""

from __future__ import annotations

import asyncio
import json
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

from deepagents.backends.protocol import ExecuteResponse, FileDownloadResponse, FileUploadResponse
from deepagents.backends.sandbox import BaseSandbox
from e2b.exceptions import TimeoutException


class HarborSandboxBackend(BaseSandbox):
    def __init__(self, environment, loop, stopped, logs_dir: Path, timeout: int = 120):
        self.environment = environment
        self.loop = loop
        self.stopped: threading.Event = stopped
        self.logs_dir = logs_dir
        self.timeout = timeout
        self.record_lock = threading.Lock()
        self.transfer_dir = logs_dir / "transfers"
        self.transfer_dir.mkdir(parents=True, exist_ok=True)

    @property
    def id(self) -> str:
        return str(self.environment.session_id)

    def _wait(self, coroutine, timeout: int):
        if self.stopped.is_set():
            coroutine.close()
            raise RuntimeError("Agent execution has ended")
        future = asyncio.run_coroutine_threadsafe(coroutine, self.loop)
        try:
            return future.result(timeout=timeout + 20)
        except BaseException:
            future.cancel()
            raise

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        started = monotonic()
        record = {
            "operation": "execute",
            "command": command,
            "started_at": datetime.now(UTC).isoformat(),
        }
        try:
            result = self._execute(command, timeout=timeout)
            record.update(
                exit_code=result.exit_code,
                output_chars=len(result.output),
                truncated=result.truncated,
            )
            return result
        except Exception as exc:
            record["error_type"] = type(exc).__name__
            raise
        finally:
            record["duration_seconds"] = monotonic() - started
            with self.record_lock, (self.logs_dir / "environment-events.jsonl").open("a") as stream:
                stream.write(json.dumps(record) + "\n")

    def _execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        limit = min(timeout or self.timeout, self.timeout)
        try:
            result = self._wait(self.environment.exec(command=command, timeout_sec=limit), limit)
        except (TimeoutError, TimeoutException):
            return ExecuteResponse(
                output="Command timed out; inspect the current state before retrying.",
                exit_code=124,
                truncated=False,
            )
        return ExecuteResponse(
            output=(result.stdout or "") + (result.stderr or ""),
            exit_code=result.return_code,
            truncated=False,
        )

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        responses = []
        with tempfile.TemporaryDirectory(dir=self.transfer_dir) as folder:
            for index, (path, content) in enumerate(files):
                local = Path(folder) / str(index)
                local.write_bytes(content)
                self._wait(self.environment.upload_file(local, path), self.timeout)
                responses.append(FileUploadResponse(path=path))
        return responses

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        responses = []
        with tempfile.TemporaryDirectory(dir=self.transfer_dir) as folder:
            for index, path in enumerate(paths):
                local = Path(folder) / str(index)
                self._wait(self.environment.download_file(path, local), self.timeout)
                responses.append(FileDownloadResponse(path=path, content=local.read_bytes()))
        return responses
