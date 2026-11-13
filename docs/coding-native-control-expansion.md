# Second native control batch

This batch covers 23 further tasks whose official reference programs do not download
additional packages or public inputs. Source inspection uses the pinned Terminal-Bench
2.1 revision in `configs/coding-tasks.lock.json`. This is environment acceptance with no
model calls; its results are separate from the HIGH, one-attempt model study.

The capture registry adds each task's working directory. `prove-plus-comm` uses
`/workspace`; `multi-source-data-merger` also captures `/data` to preserve evidence of
input changes. Other selected tasks use `/app`. Only changes since the actor baseline
are archived; original large model weights and compiler trees are not copied into each
submission unless modified.

Each task receives four independent controls: offline/public crossed with empty/reference.
The official tests must execute, give the expected zero/one reward, and complete verified
instance cleanup. The receipt preserves every failure and records source, cache and
configuration hashes. These controls do not consume model samples.

Selected tasks:

- `break-filter-js-from-html`
- `circuit-fibsqrt`
- `custom-memory-heap-crash`
- `distribution-search`
- `feal-differential-cryptanalysis`
- `feal-linear-cryptanalysis`
- `filter-js-from-html`
- `fix-ocaml-gc`
- `gpt2-codegolf`
- `llm-inference-batching-scheduler`
- `make-mips-interpreter`
- `model-extraction-relu-logits`
- `multi-source-data-merger`
- `password-recovery`
- `path-tracing`
- `path-tracing-reverse`
- `portfolio-optimization`
- `prove-plus-comm`
- `query-optimize`
- `regex-chess`
- `sanitize-git-repo`
- `schemelike-metacircular-eval`
- `vulnerable-secret`


## Recorded batch outcome and targeted repairs

Job `1208155` ended with 90/92 accepted controls and all 92 instances confirmed deleted. The two failures were offline references for `filter-js-from-html` and `fix-ocaml-gc`. Their original rewards and logs remain unchanged. The other 21 tasks passed all four controls each.

The HTML task now has a verified public-data cache and explicit installed-driver selection; job `1208208` passed four fresh controls. The OCaml task now uses a verifier-only bare Git mirror at commit `356d558bf89552ed9229253ec4135c691234f060`; job `1208230` passed all four fresh controls, including the offline reference. Its 7,415,482-byte archive has SHA-256 `07aaf65edbc8ee77304271f5552e9914f64f47a54376a8da900ca788f4e7d342`. Only the exact official clone URL is redirected, and only after actor submission. Public Git preparation job `1208224` verified offline cloning, the pinned commit and testsuite, then confirmed instance deletion. The earlier server-side Git transport failure is preserved.

The HTML diagnostic also demonstrated false acceptance of a deliberately incorrect implementation. See [the matched case and evidence](case-offline-browser-false-acceptance.md). All preparation, reference and diagnostic runs in this section made zero model calls.
