# Continue the full study without resampling

An expansion selection can list `prior_studies` in execution order. Each entry
contains the prior checkout root, its study path and the frozen study SHA-256.
Preparation checks the same full-task configuration, model profile and pilot,
verifies the previous runtime files, and accounts for every previously scheduled
task/network/group cell exactly once. It snapshots each prior plan.

New task selections cannot overlap those reservations. Already scheduled tasks
are recorded as `reserved_prior_tasks` and excluded from `pending_tasks`.
The accounting identity remains pilot cells + reserved earlier cells + new cells
+ remaining cells = 890. Valid zero scores remain part of their original batch;
this mechanism does not retry them.

Schedule the next array with `afterany:<previous-array-id>` and the same array
concurrency of two. Slurm releases this dependency only after every element of
the preceding array has ended, as documented in its
[job array dependency reference](https://slurm.schedmd.com/job_array.html).
This keeps the combined actor concurrency at two while allowing later tasks to
proceed even if an earlier task reported an error. Those earlier errors remain
in the study ledger for explicit diagnosis.

Each new execution unit still requires the complete six-task pilot evidence,
its own frozen source and model settings, and four accepted environment controls
for the selected task. The live first-array checkout is unchanged.
