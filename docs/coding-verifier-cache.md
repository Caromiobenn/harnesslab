# Offline verifier prerequisites

Native task profiles declare a separate `verifier` cache. It contains public package
artifacts and download receipts; official tests are uploaded by Harbor after submission.
Both network arms use the same cache. Required submitted services remain alive and the
actor's network mode stays in effect while the official verifier runs.

The adapter installs hash-checked archives after the actor finishes, supplies the pinned
uv bootstrap, and maps only explicitly recorded download URLs to local files. The curl
wrapper retains the original flags and delegates all other URLs unchanged. In particular,
requests to a task's local service still reach that service. Official test files and
assertions remain unchanged. Each cache records the actual resolved artifacts, including
transitive dependencies, so a later index update cannot silently change the frozen cache.

Python and system-package resolution must use the prepared local caches in both arms.
Do not set `PIP_NO_INDEX` globally: a test may install a submitted package from a local
PyPI service with `--index-url`. Use a local default index plus local wheel links so
explicit task-service indexes continue to work.

The adapter and transport unit test alone do not prove all 89 tasks can run offline.
Each task still needs a matching empty/reference acceptance with its declared cache.

## Verified service task

CPU job `1207978` completed the official Harbor `pypi-server` controls on 2026-11-14
(Asia/Shanghai), using the fixed Terminal-Bench 2.1 revision. Empty scored 0 with one
executed, failed test; reference scored 1 with one executed, passed test. The verifier
downloaded `vectorops==0.1.0` from the submitted local service and installed it successfully.
The two cloud instances were deleted and their absence confirmed through the management
API. No model was called. The receipt is
`artifacts/coding/tb21-native-pypi-offline-v2-20261114/acceptance.json`.

The task's pinned cache manifest is `configs/coding-native-pypi.lock.json`. The actor
receives a local APT repository and Python wheels; the reference still performs its
original installation, package building, server startup and upload steps while offline.
Preparation scripts and resolved package inventories are retained under
`artifacts/setup/tb21-pypi-actor-cache-v2-20261114` and
`cache/coding-native/pypi-server-v2/files.json`. Only public dependencies entered these
caches; preparation did not execute the reference solution.

This acceptance also exercised passing newly prepared cache variables into commands
after instance creation. Updating a startup configuration dictionary alone was insufficient
for the installed Harbor version; the adapter now merges those variables per command.
The stage passed 143 tests, Ruff checks and the existing smoke validation.
