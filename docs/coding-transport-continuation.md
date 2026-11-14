# Continuing the study after a transport amendment

The streaming adapter passed 208 tests and the offline smoke check. A separate
CPU canary (`1208559`) then exercised the real configured API with the native
mini and Deep Agents adapters: each used one request and returned token usage.
Mini's streamed response included a parsed tool call and 180 reasoning
characters. Deep Agents returned the requested 12-character marker; that short
response contained zero reasoning characters. These are transport checks, not
additional benchmark attempts or evidence about long-task accuracy.

Replacement plans accept a `transport_amendment` selection record. They require
the old queues to be terminal, freeze the queue-retirement and API-canary
receipts, compare every model/protocol setting other than response transport,
and verify the original source and outcome hashes. Completed task cells are
retained whether their reward is one, zero, or unavailable after an API error.
The replacement must include every unstarted task and exclude every attempted
task. An incomplete execution unit requires reconciliation before replacement.

The six-task pilot remains the existing 60-cell experiment. Its preflight gate
now explicitly checks for a declared transport difference and verifies the
associated receipts. New units run with streaming for all five groups and
retain HIGH, N=1, the original task budgets, and concurrency two. Reports must
identify the pilot/early non-streaming cohort separately from the replacement
cohort when analyzing transport-sensitive failures or costs.

The original API failures keep their missing scores until their saved
submissions are independently graded. Known response usage is retained;
provider usage for the interrupted request is not assumed to be zero. Recovery
of a missing score must use the saved submission without calling the actor
model again.
