# Regrading unchanged submissions after request failures

Six early `adaptive-rejection-sampler` cells ended with an API read timeout
after three or four received model responses. Harbor skipped verification on
that uncaught actor error. Every affected trial retained a verified filesystem
delta for `/app`; all six deltas contain no changes or deletions. Their
original missing scores, exceptions, usage, and trajectories remain immutable.

The artifact-only regrader validates the saved manifest, archive and baseline
hashes, then creates a fresh instance with the same pinned task image and
prerequisite bytes. It requires the captured filesystem baseline to match,
checks that the fresh submission remains unchanged, and lets Harbor execute
the unchanged official verifier in the original network arm. It makes zero
actor-model calls. Scores and official test counts are written to a separate
regrade ledger referencing the original cell and artifacts.

This mechanism applies to unchanged filesystem submissions. It does not replay
agent commands, restore VM memory, or reconstruct arbitrary changes outside
the declared capture paths. For these six cells, the relevant missing
deliverables are in `/app`; official assertions determine their scores.
The original API failure remains a harness error even after recovering a
score. Usage from received responses stays attached to the original trial;
unreported usage of the interrupted request is not treated as zero.
