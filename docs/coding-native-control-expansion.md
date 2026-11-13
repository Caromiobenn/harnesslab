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
