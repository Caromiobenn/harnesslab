# C4 official verifier dataset cache

The task image contains the official sample from shard 00000. Its verifier generates a separate
test input from shard 00009, then checks directory size, file size, reconstructed filenames and
content hashes. The new preparation caches only that public dataset dependency, using the
official `datasets==3.6.0` environment and the unmodified `load_dataset` call.

The upstream repository revision is `1588ec454efa1a09f29cd18ddd04fe05fc8653a2`.
The 318,185,592-byte shard has SHA-256
`807a548efbb10153c9eff0df5733a97a1b51ab1743242530de1b02a8ea17ace7`.
Preparation verifies those bytes, compares the pinned and default loads, then disables internet
and repeats the exact default load, requiring the same row count, columns and dataset fingerprint.

The cache is attached through the existing `verifier_inputs` ledger family and transferred only
after actor submission. It contains public dataset caches, not generated test directories, solution
scripts or expected answer files. The actor continues to see only the original image's sample.
Empty/reference controls must pass in both network modes before the task receives model attempts.

Sources: [repository revision](https://huggingface.co/datasets/allenai/c4/commit/1588ec454efa1a09f29cd18ddd04fe05fc8653a2),
[official shard and SHA-256](https://huggingface.co/datasets/allenai/c4/blob/1588ec454efa1a09f29cd18ddd04fe05fc8653a2/en/c4-train.00009-of-01024.json.gz).

Preparation uses the imported task directory returned by `task_plan`, which verifies every file
against the pinned lock. The external dataset argument is checked for the benchmark revision;
its absolute directory need not equal the worktree-local imported copy. The first preparation
(job 1209570) stopped at the old directory-equality check before creating any cloud instance.
