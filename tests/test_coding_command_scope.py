"""A live service launched by a completed command is distinct from an active tool."""

import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("e2b")
from e2b import CommandExitException

from harnesslab.coding.command_scope import ActorCommandScope


class Commands:
    def __init__(self):
        self.killed = []

    async def kill(self, pid, **kwargs):
        self.killed.append(pid)
        return True


class Handle:
    def __init__(self, pid, exception=None):
        self.pid, self.exception = pid, exception

    async def wait(self):
        if self.exception:
            raise self.exception
        return SimpleNamespace(exit_code=0, stdout="started service")


async def start(handle):
    return handle


def test_completed_service_launcher_is_preserved_and_active_command_is_stopped():
    async def scenario():
        commands = Commands()
        scope = ActorCommandScope(commands)
        launcher = await scope.dispatch(lambda: start(Handle(101)))
        await launcher.wait()
        await scope.dispatch(lambda: start(Handle(202)))
        result = await scope.close()
        assert commands.killed == [202]
        assert result["closed"]
        assert await scope.close() == result
        with pytest.raises(RuntimeError, match="closed"):
            await scope.dispatch(lambda: start(Handle(303)))

    asyncio.run(scenario())


def test_nonzero_exit_is_terminal_but_a_transport_error_is_not():
    async def scenario():
        commands = Commands()
        scope = ActorCommandScope(commands)
        failed = await scope.dispatch(
            lambda: start(
                Handle(
                    101,
                    CommandExitException(stdout="", stderr="test failed", exit_code=1, error=None),
                )
            )
        )
        with pytest.raises(CommandExitException):
            await failed.wait()
        lost = await scope.dispatch(lambda: start(Handle(202, ConnectionError("stream ended"))))
        with pytest.raises(ConnectionError):
            await lost.wait()
        await scope.close()
        assert commands.killed == [202]

    asyncio.run(scenario())


def test_close_waits_for_dispatch_then_stops_the_returned_handle():
    async def scenario():
        commands = Commands()
        scope = ActorCommandScope(commands)
        started, release = asyncio.Event(), asyncio.Event()

        async def delayed():
            started.set()
            await release.wait()
            return Handle(404)

        dispatch = asyncio.create_task(scope.dispatch(delayed))
        await started.wait()
        close = asyncio.create_task(scope.close())
        await asyncio.sleep(0)
        assert not close.done()
        release.set()
        await dispatch
        await close
        assert commands.killed == [404]

    asyncio.run(scenario())


def test_native_group_cleanup_surrounds_sdk_stop_for_distinct_id_namespaces():
    async def scenario():
        events = []

        class RemoteCommands:
            async def kill(self, pid, **kwargs):
                events.append(("sdk_stop", pid))
                return False

        async def native_cleanup():
            events.append(("native_group", 300))
            return {"identity": {"pid": 300}, "remaining_native_pids": []}

        scope = ActorCommandScope(RemoteCommands())
        await scope.dispatch(lambda: start(Handle(4)), native_cleanup)
        result = await scope.close()
        assert events == [("native_group", 300), ("sdk_stop", 4), ("native_group", 300)]
        assert result["stopped_commands"][0]["sdk_command_id"] == 4

    asyncio.run(scenario())
