# Public package installers for offline actors

Some tasks explicitly require an agent to install packages. Their fixtures contain
downloaded public installer files, not an already-installed task environment. The
same files and pip discovery settings are supplied to both network arms. The agent
still performs installation, implementation and service startup.

`prepare_coding_actor_wheels.py` downloads pinned public packages using the task
image's Python. In that disposable preparation instance, it disables internet,
runs the ordinary pip installation command and imports the required modules.
Only `/opt/harnesslab-public-wheels` is archived; installed packages, task answers
and reference code are not included. Receipts retain every downloaded file's hash,
the resolved environment, offline installation output and instance cleanup result.

Runtime pip uses `PIP_FIND_LINKS` for local installers, with zero retries and a
five-second index timeout. The public index remains configured in both arms; these
settings let a normal pip command find cached pins without long offline retries.
No install command is added to the native environment's pre-actor setup.

The package profiles distinguish task-explicit versions (gRPC) from public library
versions selected from the reference runtime (EigenPy and the dataset/tokenizer
libraries). This dependency provisioning is part of the recorded experimental
environment. It does not contain a solution program or computed task result.

Data/model snapshots required by other tasks are a separate fixture preparation.
For `count-dataset-tokens`, the public instruction requests the
`Qwen/Qwen2.5-1.5B-Instruct` tokenizer and the `ryanmarten/OpenThoughts-1k-sample`
dataset, despite using the phrase “deepseek tokens” in its question.


## Verified preparation and fresh-instance controls

Job `1208126` prepared all three package sets and installed/imported them offline in
disposable task images; all three instances were confirmed deleted. Archive inspection
confirmed that only the public installer directory was saved.

Job `1208132` then completed eight official controls in fresh instances for gRPC and
EigenPy: offline/public crossed with empty/reference. Every empty submission scored
0 and every reference scored 1, with official assertions executed and all instances
confirmed deleted. References performed their original pip installation commands and,
for gRPC, started the required background service. This verifies archive reuse outside
the package-download preparation instance. No model calls were made.

The dataset-token-count task has its installer cache prepared; its dataset/tokenizer
fixtures and official task controls are separate remaining steps. This stage passed
159 tests, 85.70% coverage, Ruff and smoke validation.
