"""Reconnect silent official reference commands without dispatching them twice."""
import time
from e2b.exceptions import TimeoutException


class ReconnectingOracleHandle:
    def __init__(self, handle, commands, deadline, logger):
        self.handle = handle
        self.commands = commands
        self.deadline = deadline
        self.logger = logger
        self.pid = handle.pid

    async def wait(self):
        for attempt in range(9):
            try:
                return await self.handle.wait()
            except TimeoutException:
                remaining = self.deadline - time.monotonic()
                # Oracle redirects both streams to its persisted log. Do not
                # merge arbitrary interactive output or restart a lost process.
                if (attempt == 8 or remaining <= 1 or self.handle.stdout or self.handle.stderr):
                    raise
                self.logger.warning('Reconnecting silent oracle PID %s with %.1fs remaining', self.pid, remaining)
                self.handle = await self.commands.connect(self.pid, timeout=remaining, request_timeout=min(60, remaining))


def oracle_handle(handle, commands, command, timeout_sec, started_at, logger):
    if (timeout_sec and timeout_sec >= 900 and '/solution/solve.sh' in command
            and '> /logs/agent/oracle.txt 2>&1' in command):
        return ReconnectingOracleHandle(handle, commands, started_at + timeout_sec, logger)
    return handle
