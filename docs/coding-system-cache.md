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

Installation uses APT's dependency resolver with local `.deb` paths and
`--no-download`, with `Dir::Cache::archives` pointing to the same downloaded archive
directory. This respects package pre-dependencies, including the Python minimal
interpreter required before the `python3-minimal` wrapper can be unpacked. The
instance's internet access is already disabled during this check. A successful probe
records the exact installation command for later restoration in a fresh task image.

For images without a CA certificate package, preparation supplies the controller's
versioned certifi public trust bundle through APT's `Acquire::https::CaInfo` option.
The receipt records the certifi version and bundle SHA-256. HTTPS certificate checking
and package signature verification remain enabled. The bundle is used by preparation;
the cached package archive is installed after the actor submits.

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


## Verified package pre-dependency ordering

CPU job `1208071` successfully installed the cached official verifier package closures
for `make-doom-for-mips` and `pytorch-model-cli` with internet disabled. Both previously
failed because a single `dpkg -i` pass tried to unpack Python wrapper packages before
their required minimal interpreter was configured. The installer now uses APT's local
dependency ordering with `--no-download` and the recorded archive directory. Both
preparation instances were confirmed deleted. This stage passed 147 tests, Ruff and
smoke validation; it made no model calls.

The initial APT probe (`1208060`) retained failure records because it still used APT's
default archive directory. Successful retry records and exact package checksums are in
`artifacts/coding-system-caches/tb21-system-order-accept-20261114b/`. The original failed
attempts remain separate. See the [APT reference](https://manpages.debian.org/bookworm/apt/apt-get.8.en.html)
for `--no-download` and `Dir::Cache::archives`.
