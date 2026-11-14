# Third native control batch

This batch covers 13 further tasks whose official reference programs do not download
additional packages or public inputs. Source inspection uses the pinned Terminal-Bench
2.1 revision in `configs/coding-tasks.lock.json`. This is environment acceptance with no
model calls; its results are separate from the HIGH, one-attempt model study.

All selected instructions place submissions under `/app`. The runtime records only
changes since the actor baseline. Image-provided media, weights, libraries and compilers
remain the original task inputs. Public verifier installers come from the accepted
shared/custom Python and system-package ledger.

Each task receives four independent controls: offline/public crossed with empty/reference.
The official tests must execute, give the expected zero/one reward, and complete verified
instance cleanup. The receipt preserves every failure and records source, cache and
configuration hashes. These controls do not consume model samples.

Selected tasks:

- `code-from-image`
- `extract-moves-from-video`
- `modernize-scientific-stack`
- `polyglot-rust-c`
- `pytorch-model-recovery`
- `reshard-c4-data`
- `sparql-university`
- `torch-pipeline-parallelism`
- `torch-tensor-parallelism`
- `tune-mjcf`
- `video-processing`
- `winning-avg-corewars`
- `write-compressor`
