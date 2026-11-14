# Chess and G-code public installers

The `chess-best-move` and `gcode-to-text` profiles pin the Python package versions
listed by the benchmark reference installation commands. They contain public
installers only. Task solutions, intermediate outputs and answer files are excluded.

The wheel builder now resolves either image Python name (`python` or `python3`).
The chess preparation probe uses the reference's explicit system-package flag on
Ubuntu. The G-code probe installs the accepted public APT packages before importing
OpenCV, so its native-library imports are checked with internet access disabled.

System packages are installed only in the disposable preparation instance. The
returned wheel archive contains installers, and model trials still begin from the
task image with ordinary installation commands available. APT and wheel caches are
supplied identically to both network arms; the online arm retains its public indexes.

Pass `--cache-ledger` to `prepare_coding_actor_wheels.py` for these two profiles.
Receipts retain package versions, archive hashes, the system-cache receipt hash,
the offline import results, and verified instance cleanup. Official empty/reference
controls remain the separate acceptance gate for task readiness.
