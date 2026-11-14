# Full HIGH study execution

The study scope remains all 89 pinned Terminal-Bench 2.1 tasks, five groups and two
network conditions: 890 model cells at one attempt per cell. The six-task pilot's
60 scored cells are preserved. Remaining tasks enter execution as their four native
empty/reference controls pass; unready tasks remain explicitly listed in the plan.

`prepare_coding_expansion.py` freezes selected control snapshots, exact public-cache
entries, model settings, runtime hashes and execution-unit configurations. Existing
public archives are hash-checked and hard-linked. No models run during preparation.

Execution units preserve the official per-task agent and verifier limits. Groups
are split when their controller timeout bounds would exceed a 12-hour CPU job.
A Slurm array with concurrency two bounds simultaneous model execution; no GPU is
requested. Each unit has a unique batch name and no automatic requeue.

Before launching any new model cell, `run_coding_expansion_unit.py` requires the
complete pilot matrix, matching HIGH/sampling/budget settings, all requested usage
and timing measurements, verified cleanup, and LangSmith feedback for Deep Agents.
Valid zero scores are retained. Original unscored setup failures remain linked to
their records. An incomplete pilot or changed configuration stops expansion before
model execution.

Accepted native controls are reused with their original evidence. New model cells
keep their original trajectories, submissions, scores and metrics in the normal
batch directories. Local report aggregation includes the preserved pilot and each
completed expansion batch; scheduling does not reset the study denominator.
