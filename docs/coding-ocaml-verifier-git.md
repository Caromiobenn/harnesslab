# Pinned public Git input for the OCaml verifier

The official `fix-ocaml-gc` verifier clones `https://github.com/sadiqj/ocaml/` and checks
out `tag_purposefully_broken_sweeping_changes`. Offline controls previously failed before
the OCaml testsuite ran. The public source is now pinned to commit
`356d558bf89552ed9229253ec4135c691234f060` and prepared as a bare repository.

Preparation uses an isolated instance to download the public tag, verifies the commit
and Git object integrity, disables internet, and proves that an ordinary clone plus
checkout still works. The repository and its resolved hash are saved before deleting
the preparation instance. The first accepted archive was 7,415,482 bytes with SHA-256
`07aaf65edbc8ee77304271f5552e9914f64f47a54376a8da900ca788f4e7d342` (job `1208224`).

The `verifier_inputs` cache family transfers this archive only after actor submission.
Verifier-specific Git configuration rewrites only the exact official clone URL to its
local bare mirror. The actor does not receive this testsuite source or Git setting.
The original test script, tag checkout and assertions remain unchanged.

Job `1208230` passed all four new offline/public empty/reference controls, with every
instance confirmed deleted. The original offline clone failure and the earlier
server-side download failure remain in their own records.

```bash
python scripts/prepare_coding_ocaml_verifier.py \
  --dataset /path/to/pinned-dataset \
  --run ocaml-verifier-public-git
```

The script checks the benchmark revision and official test-script hash. Its output is
an accepted cache receipt; the ledger records that receipt's hash, origin root and
archive. This preparation makes no model calls.
