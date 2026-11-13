# CompCert actor toolchain startup

The CompCert image does not declare a PATH entry in its captured runtime metadata.
The pilot adapter previously indexed that missing entry during agent setup. The five
offline model groups failed with `KeyError: PATH` before their first model request;
their outcomes have no official score and remain preserved as preparation failures.

The adapter now reads the actual actor shell PATH, prepends the existing pinned OPAM
toolchain and passes PATH, OPAMROOT and OPAMSWITCH on actor tool calls. It records
those selected values in `agent/toolchain-environment.json`. Other task branches and
the existing empty/reference control paths are unchanged.

CPU job 1208059 tested fresh instances in both offline and public conditions. As UID
26000, each resolved Coq 8.16.1, OCaml 4.14.2 and menhirLib, compiled a small Coq proof,
compiled an OCaml program and ran it successfully. Network checks passed and both
instances were confirmed deleted. No model was called and no task solution was run.
The branch passed 124 tests, Ruff and smoke validation.

Evidence: `artifacts/setup/tb21-compcert-toolchain-20261114/result.json` and its two
per-network results. Existing scored pilot cells are retained. CompCert cells can be
continued only after confirming no model response exists in the failed attempt.
