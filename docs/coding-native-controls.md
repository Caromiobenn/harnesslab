# Native task control batches

The full study configuration names all 89 tasks at the pinned benchmark revision,
with HIGH reasoning and one model attempt per group/network cell. Import it with
`scripts/import_hongkong_infra.py --source SOURCE --config configs/coding-tb21-full.json`.
This imports task files and verifies their hashes; it does not run a model.

`run_coding_native_controls.py` composes each selected task's verifier profile from
the recorded public-cache ledger. It checks preparation receipts, archive bytes,
image fingerprints and unchanged official test scripts. The profile keeps public
dependencies in the verifier phase. Existing large archives are hardlinked into the
isolated runtime and checked before transfer. The exact ledger is saved with the run.

The script runs empty and official-reference controls in both offline and public
network conditions, with at most two instances active. Acceptance requires the
expected reward, at least one executed official assertion, and confirmed instance
deletion. A zero reward from a verifier that never reached assertions is not an
accepted empty control. Failure stops that task/network pair, retains its artifacts,
and lets the other pairs finish. A new run name is required after inspecting failures.

`configs/coding-native-control-profiles.json` declares task-specific capture paths.
For Git deployment these include the bare repository, SSH/Nginx configuration,
account records and deployed content. The terminal implementation also captures
system Python packages and shell startup files. Service processes retain the same
network policy through final verification; submission archives record file changes
and process metadata. Credentials and raw task artifacts remain ignored by Git.

Example (after importing tasks and supplying the recorded cache ledger):

```sh
python scripts/run_coding_native_controls.py \
  --run tb21-native-controls-batch1 \
  --cache-ledger artifacts/setup/full-verifier-cache-ledger.json \
  --task-profiles configs/coding-native-control-profiles.json
```

These controls contain no model calls. Full model execution follows six-task pilot
acceptance and each task's environment controls. Tasks still needing public input
fixtures or actor dependencies remain in the 89-task plan and are prepared separately.
