# Actor shutdown after a deadline

An offline `cancel-async-tasks / generic_retry` pilot reached its 900-second budget,
then cleanup raised `Actor processes did not exit`. Official grading and submission
capture were skipped. That original attempt remains an infrastructure failure with a
null reward; it is not relabelled as a passing or failing official result.

The old shutdown loop treated every process-table entry owned by the actor as running.
A separate zero-model cloud probe reproduced the same error by killing a child while
its parent had not yet reaped it. The remaining entry had state `Z` and uid 26000.
Such a zombie has already exited and cannot run commands; SIGKILL cannot reap it.
The original failed instance had already been cleaned up, so its exact final process
state is unavailable. The probe establishes a concrete failure mechanism in that code.

The fix ignores exited `Z`/`X` entries, kills live actor processes, and checks for up
to five seconds. A still-active process remains an error, now with its PID and state.
This runs after actor time has ended, before capture and verifier network access.
The cloud probe passed shutdown and exact submission readback, and its instance was
removed. Unit tests also check that an active process is killed, a zombie is accepted,
other users are untouched, and an unresponsive live process is reported.

Evidence: `artifacts/setup/actor-shutdown-probe-20261114/result.json`, job 1207706.
The fix is isolated on its own branch; job 1207614 retains its original frozen source.
