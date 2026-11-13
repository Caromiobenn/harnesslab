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

## Shared verifier package preparation

`scripts/prepare_coding_verifier_caches.py` groups the fixed dataset's verifier scripts
by their exact `uvx` dependency arguments. It checks each script against the dataset
provenance before reading it, preserves pinned versions and indexes, and expands only
literal shell assignments used in those arguments. It runs `pytest --version` to populate
the public package cache; it does not execute task assertions or reference solutions.

Each recipe uses a fresh cloud instance. After resolution, the script disables internet
access and checks that the same package environment starts with `UV_OFFLINE=1`. It saves
the resolved package versions, an archive checksum, the offline probe and instance cleanup
receipt. Equal recipes share one archive; task-specific system packages and public inputs
remain separate prerequisites. Scripts with a custom pip/venv setup are listed for separate
preparation. The task's own empty/reference controls remain the final readiness check.

For a bounded preparation pass, select representative tasks:

```bash
uv run --extra coding python scripts/prepare_coding_verifier_caches.py \
  --dataset /path/to/pinned-terminal-bench-2.1 \
  --run verifier-cache-acceptance \
  --tasks log-summary-date-ranges adaptive-rejection-sampler
```

Preparation uses two concurrent instances and makes no model calls. Successfully saved
recipes can be reused within the same preparation run after their archive hashes are
checked. A failed recipe retains its receipt and logs for inspection.

The bounded preparation completed in CPU job `1207997`: the common pytest recipe
(`4e8edc06fdd8`) produced a 2,584,128-byte archive, and the NumPy/SciPy recipe
(`c196ea8dbf39`) produced a 54,932,793-byte archive. Both started pytest 8.4.1 after
internet access was disabled. Archive transfer checksums matched and both instances
were confirmed deleted. Receipts are under
`artifacts/coding-verifier-caches/tb21-verifier-shared-20261114/`.
The code passed 145 tests (85.59% coverage), Ruff and the smoke validation.

Git-based dependencies retain the official pinned repository revision. The preparation
instance installs Git when the recipe requires it, records the package installation log,
then caches the built public package with the rest of the dependencies. This is preparation
tooling only; task actors still receive the declared task profile and solve the task themselves.

The MobileSAM recipe passed preparation in CPU job `1208006`, using Python 3.11 and the
official pinned MobileSAM revision `34bbbfdface3c18e5221aa7de6032d7220c6c6a1`.
Its 511,371,951-byte archive includes the managed Python installation and resolved
package cache. The same recipe started pytest 8.4.1 offline; archive transfer matched
SHA-256 `fc5d6c297c8900ffb2d790f0edfaeff100656dbf71e91a1dd60fe103c8215798`.
The preparation instance was confirmed deleted. The receipt is under
`artifacts/coding-verifier-caches/tb21-verifier-source-20261114/e1bc108605a4/`.
This verifies package preparation; task inputs, weights, system dependencies and the
official task controls are tracked separately.
