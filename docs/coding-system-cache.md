# Task-image verifier system packages

`scripts/prepare_coding_system_caches.py` downloads verifier system packages in a fresh
instance of each task's original image. It preserves the environment fingerprint and
checks the official test script against the fixed dataset provenance. Package names
come from the official verifier, rather than from a model's proposed solution.

The script downloads the package dependency closure, disables internet access and
installs the downloaded packages to check offline availability. It saves package
metadata, checksums, an archive, the offline installation log and an instance cleanup
receipt. It makes no model calls and executes no task solution or test assertions.

```bash
uv run --extra coding python scripts/prepare_coding_system_caches.py \
  --dataset /path/to/pinned-terminal-bench-2.1 \
  --run verifier-curl-acceptance \
  --tasks openssl-selfsigned-cert log-summary-date-ranges sqlite-db-truncate \
  --packages curl
```

Add each resulting archive and installation command to that task's `verifier` profile,
alongside its shared Python cache. The runtime installs these system packages after the
actor submits. Official task tests remain unchanged. Use identical packages in both
network conditions, then run empty and official-reference controls in each condition.
An offline package installation probe alone does not establish task readiness.

## Verified three-task controls

CPU job `1208017` prepared and installed the cached curl dependency closure offline
for `openssl-selfsigned-cert`, `log-summary-date-ranges` and `sqlite-db-truncate`.
The resolved curl version was `7.88.1-10+deb12u15`; all three preparation instances
were confirmed deleted.

CPU job `1208018` then ran 12 official Harbor controls: three tasks, two network
conditions, empty and reference submissions. Every empty scored 0 and every reference
scored 1; official tests executed in every trial. All cleanup checks passed. Each task
used a fresh instance, the shared Python cache and its image-specific system archive.
This also verifies restoration of the shared Python cache into fresh task images.

The task profiles are in `configs/coding-native-curl.lock.json`. Full control records
are in `artifacts/setup/tb21-native-curl-controls-20261114/acceptance.json`; package
inventories and preparation logs are in `artifacts/coding-system-caches/tb21-verifier-system-20261114/`.
No model was called. The stage passed 145 tests, Ruff and the smoke validation.
