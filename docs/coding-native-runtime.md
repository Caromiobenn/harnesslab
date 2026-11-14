# Native task runtime

The full-task runtime is selected explicitly by `runtime_profile: native` in a task's
public-prerequisite manifest. Existing six-task pilot entries retain their original
runtime. The five model groups share the selected runtime within each task.

The native profile preserves the task image's configured user, including root access
needed by package-installation and service-configuration tasks. Completed command
launchers may leave required background services running through official verification.
Outstanding foreground commands are stopped using their recorded native process-group
identity, independently of the SDK's command ID. Long reference commands retain the
vendor adapter's reconnect behavior without executing the command again.

Both empty and reference controls enter the same actor network phase as model agents.
Offline remains offline during verification while submitted services remain alive.
Consequently all required public actor assets and verifier dependencies must be cached
before the actor starts. The adapter does not silently reopen internet access for tests.
The public arm receives the same prerequisite archives and keeps internet access.

Each task declares `capture_paths`. Before the actor starts, the adapter records file
hashes and metadata. After foreground cleanup, it exports the changed files and removed
paths, verifies the transferred archive hash, and records process metadata and command
identities. This captures submitted filesystem changes, not running VM memory. Immutable
inputs remain referenced by the task template, source fingerprint, prerequisite hashes,
and baseline file manifest. Capture time is recorded separately from actor time.

This stage adds the adapter and matching controls. Full-task prerequisite preparation,
task-specific capture paths, and official reference acceptance are separate stages.
No model sampling or call budget changes are introduced here.

## Live adapter acceptance

CPU job `1207943` completed in 53 seconds on 2026-11-14 (Asia/Shanghai), using the
pinned `pypi-server` image as a capability fixture and making zero model calls. The
adapter stopped the outstanding foreground process and its child, retained the HTTP
service with response `READY`, and kept all three external-network probes blocked
after a verifier-requested public-policy switch. Its 359-byte delta archive passed
the transfer hash check and recorded one deleted file. The cloud management API
confirmed instance deletion. The receipt is
`artifacts/setup/tb21-native-runtime-probe-20261114/result.json`.

This is adapter acceptance, not the official `pypi-server` task score. The stage also
passed 139 unit tests, Ruff checks, and the existing smoke validation.
