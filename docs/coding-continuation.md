# Continue the matrix without selecting extra samples

Each task/group/network cell has one independent scored attempt. An official zero,
including a deadline result, is a completed cell. It is not a reason to call the model
again. A reviewer failure with an official score also stays in the record for diagnosis.

Generate an inventory from explicitly selected batches:

```bash
uv run --extra coding python scripts/plan_coding_continuation.py \
  --batches tb21-high-offline-20261114b tb21-high-public-20261114b \
  --output artifacts/coding-reports/continuation.json
```

The inventory checks the model snapshot/endpoint, HIGH configuration and task budgets,
links all attempts and immutable plans by hash, and rejects multiple scored attempts
for one cell. It distinguishes retained scores, unfinished stages, unstarted cells,
saved submissions to inspect for artifact-only regrading, and proven cleanup failures
that need the tested shutdown fix. Other unscored errors require diagnosis first.

This command never launches a model or creates an environment. An unfinished stage
file does not prove whether its process is running. Before executing a replacement,
verify the original owning job is terminal and its environments have been removed.
Preserve the original attempt and its cost; record the replacement's source version.
Saved-artifact regrading is a separate result and does not rewrite an original score.

The pilot currently has 60 cells: 6 tasks × 5 groups × 2 network conditions. Each arm
schedules 30 model cells and 12 empty/reference controls. Expanding to 89 tasks also
requires the full task/environment acceptance described in `coding-full-readiness.md`.

Implementations, measurement/reporting, and infrastructure repairs use separate branches.
At each verified milestone, make a focused commit, push that branch and check GitHub
Actions. Keep the source used by a live evaluation frozen; develop the next version in
an isolated worktree. Runtime artifacts and credentials remain ignored.
