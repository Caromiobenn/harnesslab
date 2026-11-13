"""Track foreground actor commands without killing completed background services."""

from __future__ import annotations

import asyncio
import base64
import json
import shlex
from uuid import uuid4

from e2b import CommandExitException

LAUNCH_GROUP = """import base64,json,os,sys
from pathlib import Path
try: os.setsid()
except PermissionError:
    if os.getpgrp()!=os.getpid(): raise
pid=os.getpid()
ticks=int(Path('/proc/self/stat').read_text().rsplit(')',1)[1].split()[19])
Path(sys.argv[1]).write_text(json.dumps({'pid':pid,'pgid':os.getpgrp(),'start_ticks':ticks}))
os.execv('/bin/bash',['bash','-c',base64.b64decode(sys.argv[2]).decode()])
"""

STOP_GROUP = """import json,os,signal,sys,time
from pathlib import Path
record=Path(sys.argv[1])
if not record.exists():
    print(json.dumps({'record_present':False}));raise SystemExit(0)
identity=json.loads(record.read_text());pgid=identity['pgid']
if pgid!=identity['pid'] or pgid<=1: raise RuntimeError('Invalid actor process group')
def members():
    found=[]
    for path in Path('/proc').glob('[0-9]*/stat'):
        try:
            fields=path.read_text().rsplit(')',1)[1].split()
            if int(fields[2])==pgid and fields[0] not in ('Z','X'):
                if int(fields[19])<identity['start_ticks']:
                    raise RuntimeError('Process group identity predates actor launch')
                if (int(path.parent.name)==identity['pid']
                        and int(fields[19])!=identity['start_ticks']):
                    raise RuntimeError('Actor process ID was reused')
                found.append(int(path.parent.name))
        except (FileNotFoundError,ProcessLookupError): pass
    return found
before=members()
if before:
    try: os.killpg(pgid,signal.SIGKILL)
    except ProcessLookupError: pass
for _ in range(50):
    remaining=members()
    if not remaining: break
    time.sleep(.1)
if remaining: raise RuntimeError('Actor group still running: '+repr(remaining))
print(json.dumps({'record_present':True,'identity':identity,'stopped_native_pids':before,
                  'remaining_native_pids':remaining}))
"""


def process_group_command(sandbox, command, python="python3"):
    """Return a wrapped shell command and an idempotent native-group cleanup callback.

    SDK command IDs need not equal Linux PIDs. The launcher records its own native
    process/session identity before executing the user's command.
    """
    record = "/tmp/harnesslab-command-" + uuid4().hex + ".json"
    encoded = base64.b64encode(command.encode()).decode()
    wrapped = " ".join(
        shlex.quote(value) for value in (python, "-I", "-S", "-c", LAUNCH_GROUP, record, encoded)
    )

    async def cleanup():
        script = " ".join(
            shlex.quote(value) for value in (python, "-I", "-S", "-c", STOP_GROUP, record)
        )
        result = await sandbox.commands.run(script, user="root", timeout=15)
        return json.loads(result.stdout)

    cleanup.record_path = record
    return wrapped, cleanup


class TrackedCommand:
    def __init__(self, handle, scope):
        self.handle = handle
        self.scope = scope

    def __getattr__(self, name):
        return getattr(self.handle, name)

    async def wait(self):
        try:
            result = await self.handle.wait()
        except CommandExitException:
            self.scope.active.pop(self.handle.pid, None)
            raise
        else:
            self.scope.active.pop(self.handle.pid, None)
            return result
        # A transport error/cancellation is not a process-exit observation. Retain
        # that handle so closing the actor scope can stop the outstanding command.


class ActorCommandScope:
    """Own SDK command handles only; completed launchers may leave required services alive."""

    def __init__(self, commands):
        self.commands = commands
        self.active = {}
        self.closed = False
        self.lock = asyncio.Lock()
        self.stopped = []

    async def dispatch(self, start, cleanup=None):
        # Closing waits for in-flight dispatch to return a handle, so a command
        # cannot appear after the stop snapshot and escape deadline cleanup.
        async with self.lock:
            if self.closed:
                raise RuntimeError("Actor command scope is closed")
            handle = await start()
            self.active[handle.pid] = (handle, cleanup)
            return TrackedCommand(handle, self)

    async def close(self):
        async with self.lock:
            self.closed = True
            for pid, (_handle, cleanup) in list(self.active.items()):
                if pid not in self.active:
                    continue
                native_before = await cleanup() if cleanup else None
                killed = await self.commands.kill(pid, request_timeout=15)
                # A very early stop may precede the launcher's identity record.
                # Check again after the SDK stop to collect any just-started children.
                native_after = await cleanup() if cleanup else None
                self.stopped.append(
                    {
                        "sdk_command_id": pid,
                        "killed": killed,
                        "native_before": native_before,
                        "native_after": native_after,
                    }
                )
                self.active.pop(pid, None)
        return {"closed": self.closed, "stopped_commands": list(self.stopped)}
