# Full-dataset expansion inventory

The pinned Terminal-Bench 2.1 revision is
`12b7565679ce5006230b820666353673a133db93`.
The read-only inventory on 2026-11-14 verified all task file hashes and found existing
Hong Kong template mappings for all 89 tasks. All task definitions request zero GPUs.
The authoritative inventory is `artifacts/setup/full-dataset-inventory.json` on the
controller; this check did not launch full-dataset model trials.

The final matrix is 89 tasks × five groups × two network conditions × one independent
attempt = 890 model cells. Retain valid pilot cells and expand to the remaining 83 tasks
(830 additional model cells), provided their frozen protocol remains compatible.
Keep infrastructure failures and interrupted attempts in a separate attempt ledger;
never rerun a valid failed solution to select a better score.

Before extending the six-task runtime, address task semantics found in public instructions:

| Requirement | Examples | Work required |
|---|---|---|
| A service must remain alive for grading | configure-git-webserver, hf-model-inference, install-windows-3.11, mailman, nginx-request-logging, pypi-server, qemu-alpine-ssh, qemu-startup | Preserve required service/VM state across the actor-to-verifier transition; the pilot's unconditional process termination cannot be reused unchanged |
| Write outside `/app` or configure system services | nginx-request-logging, mailman, configure-git-webserver, build-pov-ray | Specify task-appropriate permissions and save all required configuration/install paths |
| Public model, dataset, or source download | count-dataset-tokens, hf-model-inference, mteb-retrieve, sam-cell-seg, build-pov-ray | Pin public dependency/source artifacts, provision identical fixtures in both network arms, and preserve the actual task-solving work |
| Historical external information is task input | mteb-leaderboard | Provide a dated public input snapshot for the offline arm; distinguish legitimate task research from benchmark-answer access |
| Long-running compilation | build-pov-ray has a 12,000-second actor budget | Shard jobs using actual actor/verifier budgets instead of assuming every task takes 900 seconds |

These are preparation requirements, not task exclusions. Every task still requires empty
and official-reference controls in its prepared environment before model cells run.
Task-specific lifecycle and permission choices must be identical across all five groups
and both network arms, recorded with the source/configuration hashes.

The sum of the official actor budgets is 151,950 seconds per complete group/network pass,
or 422.08 sandbox hours across ten passes. This is a budget ceiling, not an elapsed-time
prediction; it excludes setup, verification, and artifact capture. Keep controller jobs
within their wall-time limit and use the persistent cell ledger to continue without
duplicating completed model work.

The existing pilot runtime and source hashes stay frozen while its job is active.
Independent full-dataset dependency preparation can proceed while the pilot runs.
Full-dataset model trials follow pilot acceptance and matching task controls.
