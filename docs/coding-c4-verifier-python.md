# C4 verifier subprocess Python selection

The official C4 verifier starts pytest through `uvx -p 3.13` with `tqdm==4.67.1`,
then starts the submitted scripts through child `uv run` commands. The shared cache adapter
also set `UV_PYTHON` to a standalone bootstrap interpreter. That extra setting caused the
child command to select an interpreter without the official verifier's dependencies.

A fresh native-image canary, job `1209492`, compared the two choices offline with identical
package caches and the official uvx requirements. With the override, the child failed with
`ModuleNotFoundError: No module named 'tqdm'`. After removing it, `uv run` selected the
environment exposed by uvx and passed. The instance was deleted and confirmed absent.

The C4 verifier profile now explicitly removes only `UV_PYTHON`. A null value in
`verifier_env` removes that variable after the adapter combines its environment settings.
The official `-p 3.13`, submitted project configuration and normal uv project selection
remain in effect. No package is added to the actor environment and no test assertion changes.

This fixes interpreter selection; full task acceptance still requires the separate official
C4 shard cache and empty/reference controls. The cache is made available only after submission.

See the upstream [uv command execution documentation](https://docs.astral.sh/uv/concepts/projects/run/).
