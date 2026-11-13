# Foreground commands and submitted services

Full Terminal-Bench coverage includes tasks that explicitly require a running
server or VM after the agent finishes. Killing every actor-owned process would
destroy a correct submission for those tasks.

`ActorCommandScope` tracks the SDK handles of foreground tool commands. Normal
completion, including nonzero exit, removes a handle. A transport exception does
not prove process exit and retains the handle for cleanup. Closing the scope
stops only the outstanding commands and rejects subsequent dispatch. An in-flight
dispatch is included before the stop operation finishes.

The real Hong Kong SDK probe found that its command ID is not the Linux PID and
that SDK `kill` leaves a command's child process alive. `process_group_command`
therefore starts each command in its own native session, records its PID/group and
process start time, and stops that group around the SDK stop. The second check
covers an identity record created concurrently with an early stop. Exited zombies
are not treated as active work. The probe retains a separate HTTP service while
checking that both a foreground command and its child have stopped.

A background service started by an already-completed command remains alive for
the verifier. This is an execution-lifecycle primitive, not a complete service
checkpoint: service processes, filesystem outputs and network transitions still
need task-specific recording. The pilot environment is unchanged. Full runtime
integration must also preserve the image's required permissions and validate
public prerequisites in both network conditions before model evaluation.

The second live probe passed on the Hong Kong `pypi-server` template: the
foreground Python process and its `sleep` child stopped, the HTTP service still
returned `READY` with external internet access disabled, and management API
verification confirmed instance deletion. Both probes used zero model calls.
Receipts: `artifacts/setup/tb21-service-scope-probe-20261114{,b}/result.json`.

Full integration must also review the control environment: the current six-task
`OracleControl` inherits the official reference runner's root execution and does
not call `begin_actor`. Its successful score alone therefore does not validate
the actor's unprivileged identity or offline dependency completeness. Preserve
the original pilot evidence and add matched phase/permission checks for full
task preparation. Required services must not gain unintended external access
when transitioning an offline actor into verification.
