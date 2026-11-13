# System pip and virtual-environment verifier caches

Six additional tasks use an explicit `pip install` or a Python 3.12 virtual environment
instead of the shared `uvx` recipes. `prepare_coding_custom_verifier_caches.py` reads the
single version-pinned installation command from the unchanged official test script and
checks that script against the pinned benchmark source inventory.

For system-pip tasks it downloads wheels with the original task image's Python, disables
internet access, installs those wheels and checks that pytest starts. It retains the
official `--break-system-packages` option where present. For the Mailman verifier it
prepares the requested Python 3.12 environment and package cache, then installs into a
second new virtual environment offline. No task assertions or reference solution run
during package preparation.

The receipt records resolved Python/package versions, wheel and archive checksums,
the offline installation result and instance cleanup. The saved wheels or uv cache
are restored only after the actor finishes. Each task retains its original interpreter
and official test command. Pip's no-index setting applies only to these verifier
profiles; the local PyPI-server task keeps its own profile and local HTTP test traffic.

Verifier transport also reads the live shell PATH, so an image without an explicit
PATH metadata entry can still use its existing commands together with cached downloads.
Both network arms use the same public dependencies. Empty and official-reference
controls remain required before model trials.


## Verified preparation and official controls

Job `1208086` prepared and installed the pinned public dependencies for
`fix-code-vulnerability` and `mailman` with internet disabled in fresh instances.
Both package checks passed and both instances were confirmed deleted. The former
used the task image's Python 3.11.18; the latter used Python 3.12.3 in a second,
new virtual environment. The receipts retain package versions and archive hashes.

Job `1208092` then ran unchanged official tests for `fix-code-vulnerability`:
both offline and public arms scored the empty submission 0 and the official
reference 1. The additional verifier executed six tests in each control, and
all four instances were confirmed deleted. No model calls were made.

The same job's separate `polyglot-c-py` empty controls stopped before assertions:
the shared uvx cache had been prepared on an image containing system Python 3.13
and did not include that interpreter for other images. Those two failed controls
and cleanup records are retained; their reference controls were not started.
Portable interpreter coverage is a separate follow-up, not a passing task result.

This stage also incorporates the separately validated CompCert actor PATH fix.
It passed 153 tests, 85% coverage, Ruff and smoke validation. Raw receipts remain
under `artifacts/coding-custom-verifier-caches/tb21-custom-verifier-accept-20261114/`
and `artifacts/setup/tb21-native-custom-controls-20261114/`.
