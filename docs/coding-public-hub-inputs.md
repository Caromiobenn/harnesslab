# Pinned public model and dataset inputs

The offline and public arms receive identical archives of public task inputs. The
repository revisions and selected files are recorded in `configs/coding-public-hub-inputs.json`.
They were resolved from the public Hub API in a disposable task instance. Preparation
downloads by full commit, records file hashes and checks normal library loading after
internet access is disabled. It does not calculate token counts, create a sentiment
service, or write task answer files.

`count-dataset-tokens` uses the Qwen2.5-1.5B-Instruct tokenizer specified in the task,
not a DeepSeek tokenizer. Only tokenizer files are downloaded; its model weights are
unnecessary. Both default and metadata configurations of the named public dataset are
cached without computing the science-domain answer.

`hf-model-inference` caches the public DistilBERT weights and tokenizer. Both canonical
and short repository identifiers resolve to the same pinned snapshot. The actor still
must save the requested model directory, implement the Flask API and run its service.

The archive contains only `/opt/harnesslab-public-hub`. Public package installers are
separate; preparation installs them only in its disposable instance. The model trials
receive installer archives and public data, not the preparation environment's installed
packages or reference solutions. Both arms share cache paths and timeout settings.
Only these prepared-input tasks receive Hugging Face's offline flags in the offline arm;
the dataset task also skips pip's unreachable package index in that arm. The public arm
retains normal network access. Effective overrides are recorded in each trial's network
receipt. This avoids spending the task's time budget on repeated attempts to contact a
network that the experiment has deliberately disabled. Local-server tasks such as
`pypi-server` do not receive these flags.

Hugging Face documents the [shared cache layout](https://huggingface.co/docs/huggingface_hub/guides/manage-cache)
and [revision-pinned downloads](https://huggingface.co/docs/huggingface_hub/guides/download).
Its [offline mode](https://huggingface.co/docs/huggingface_hub/package_reference/environment_variables#hfhuboffline)
skips remote version checks even when a cached file is present.
An offline loading probe and subsequent fresh-instance official controls are separate
acceptance steps. Preparation receipts retain downloads, hashes, probe output and verified
instance deletion under `artifacts/coding-public-hub-inputs/`.


The second preparation run `tb21-public-hub-offline-20261114` accepted both public input archives, including ordinary offline library loading and verified deletion of the preparation instances. The dataset task also installed its package archive offline in a fresh instance. This stage passed 163 tests and the required 85% coverage, Ruff and smoke checks. Fresh-instance official task controls remain the next acceptance step.
