# HarnessLab coding-agent experiments

This branch extends HarnessLab with a real terminal-task evaluation path. Harbor creates
fresh task environments, runs the official final verifier, and retains trajectories.
The controller uses the model API and needs no GPU.

## Frozen integration baseline

Terminal-Bench 2.1 is pinned to `12b7565679ce5006230b820666353673a133db93`.
The six integration tasks are `compile-compcert`, `build-cython-ext`,
`cancel-async-tasks`, `db-wal-recovery`, `raman-fitting`, and `regex-log`.
`configs/coding-tasks.lock.json` records the complete task file set and hashes.

`configs/coding-tb21.json` preserves the initial HIGH baseline: two groups
(`mini`, `deepagents_default`), one sample per task, 32,768 maximum output tokens,
a 240-second API request timeout, and a 120-second command timeout. It does not impose
an additional model-round limit. Earlier integration runs remain separate from the main
study because their token limits, environments, and sampling configuration differ.

Each task first runs an empty submission (expected reward 0) and the official reference
solution (expected reward 1), followed by each agent in a separate fresh environment.
Reward 0 is a valid unsuccessful solve. API, environment, and verifier failures are
integration errors. A deadline stop can still produce a valid scored submission.
The six-task set is an integration pilot, not a full benchmark score.

The installed mini distribution is `2.4.6+fc.1`. Its `agents/default.py`,
`config/mini.yaml`, and `models/litellm_model.py` Git blob hashes match upstream
`04d809ceab9d`, the revision named in the DeepSeek report. The fixed wheel and
`uv.lock` preserve the installed dependency versions. Deep Agents retains its default
tools, prompt construction, and subagents; all their model usage is counted.

## HIGH main study

The user-selected main preset is `configs/coding-tb21-study.json`.
The research question is whether review and evidence-grounded repair improve real task
completion, and whether network access changes score reliability or answer lookup.
All five agent groups use HIGH in both network conditions, following the user's latest choice.

| Setting | Main study |
|---|---|
| Provider and model | Alibaba Model Studio, `deepseek-v4.1-flash-1017` |
| Thinking | Enabled; `reasoning_effort=high` |
| Sampling | Temperature 1.0, top-p 0.95 |
| Context window | 1,048,576 tokens |
| Output limit per request | 393,216 tokens |
| Model-generation limit | 500 calls per trial, shared by actor, subagents, and reviewers |
| Samples | 3 independent samples per task and condition |
| Network axis | `offline` and `public` |
| Review budget | At most 3 candidates: initial result plus 2 repairs |
| Task budgets | Original task CPU, RAM, disk, agent and verifier deadlines |
| Controller concurrency | 2 tasks per batch |

The [DeepSeek evaluation section](https://arxiv.org/html/2609.19969v1#S5.SS3.SSS4)
provides MAX, three samples, temperature 1, top-p 0.95, 1M context, and 500 generation
rounds for Terminal-Bench 2.1. Its main evaluation disables network access.
HIGH is the deliberate difference in reasoning effort for this study. The 1017 endpoint
is a later model snapshot. The report does not specify a per-request
output cap; 393,216 is this endpoint's documented limit. See the
[provider API](https://help.aliyun.com/en/model-studio/deepseek-api) and
[model specifications](https://help.aliyun.com/en/model-studio/text-generation-model/).

This is a report-informed harness comparison. The shared 500-call budget, ordinary task
user, public prerequisite fixtures, and online arm are explicitly recorded experimental
choices. The report's published score is not treated as a reproduction target.
Actor calls, subagent calls, reviewer calls, and local checks consume the original agent
wall-clock budget. The official final verifier has its own separate task deadline.

## Five groups

| Group | Middleware / loop | Completion behavior |
|---|---|---|
| `mini` | Native mini-swe-agent `DefaultAgent` | Native submission sentinel |
| `deepagents_default` | Default `create_deep_agent` bundle | Natural stop |
| `generic_retry` | Existing `GenericRetryMiddleware` | Three candidates with generic self-review |
| `rubric_transcript` | Deep Agents `RubricMiddleware`, no reviewer tools | Rubric verdict requests repair, at most three candidates |
| `rubric_evidence` | Same rubric, evidence tools, and `EvidenceGate` | A satisfied verdict must also have fresh passing checks |

Both rubric groups assess deliverables, behavior, and verification against the public
instruction. The evidence group adds a current-evidence criterion. Its reviewer can
read public artifacts and run behavior checks. Each check records declared artifact
paths, before/after SHA-256 hashes, command, real exit status, and output. A later file
change or a new candidate invalidates old evidence. A failed check cannot be hidden by
a later passing check in the same review. Declared file coverage remains visible for audit.

The evidence gate runs after the framework grader. An unsupported satisfied verdict
requests another repair, within the same three-candidate limit. `ReviewOutcome` retains
the framework's internal final status before it is removed from public graph output.
`agent/review.json` records review decisions; `agent/summary.json` separates actor and
grader usage; `agent/events.jsonl` retains model and tool events.

Hidden tests, reference solutions, and official rewards are not inputs to review.
The official verifier runs after the actor stops. Its reward owns the reported task
score. Exhausted repairs remain a valid attempt; a reviewer failure is recorded as an
integration error. No candidate is selected using hidden scores.

## Common environment and network comparison

The existing `Caromiobenn/benchmark-sandbox-builder/.github/workflows/benchmark.yml`
remains the build entry point. Registered Aliyun Hong Kong E2B templates are reused.
`scripts/import_hongkong_infra.py` imports the existing adapter and task definitions,
with hashes in its provenance receipt. `project_paths.py` scopes runtime writes to
HarnessLab. Inference credentials stay in the controller process.

`scripts/prepare_coding_prerequisites.py` prepares public packages and untouched source
snapshots in fresh original task environments. It does not run reference solutions or
copy verifier material. Source history and preparation caches are removed. A single
fixture commit supports ordinary `git clone` for the CompCert and pyknotid public
snapshots. Both network arms receive identical archives, pinned by
`configs/coding-prerequisites.lock.json`. The manifest records archive hashes, source
fingerprints, preparation scripts, and cleanup receipts. No prepared task answer is
included; CompCert itself is not compiled during this step.

In both arms, commands and file transfers run as the same ordinary task user. The
network policy is applied by the cloud service and checked through live domain and IP
probes before the actor begins. The policy covers the actor, its subagents, and reviewers.
After actor processes stop, the controller captures declared submission files and
restores network access for the unchanged official verifier's dependencies. Thus
`offline` denotes the entire actor phase, not the controller's model API connection.

Use the same public fixtures, task budgets, model, sampling, and review settings for
each paired comparison. Network access is the only intended difference between arms.
Compare official success, valid-run counts, token usage, review decisions, and manually
confirmed answer-material access. Keep failures and interventions visible.

## Running the pilot

Fill `DEEPSEEK_API_KEY` in the ignored root `.env`; use the exact endpoint model ID.
For Alibaba Model Studio set `DEEPSEEK_API_STYLE=aliyun`. This sends `enable_thinking`
instead of the direct DeepSeek API's `thinking.type` field. `.env.sandbox` contains
the existing Hong Kong environment connection. Neither file belongs in source control.

```bash
uv sync --extra coding
uv run --extra coding python scripts/import_hongkong_infra.py \
  --source /WORK/PUBLIC/lijuanzi_work/ShaojunYin/data_engineering
uv run --extra coding python scripts/prepare_coding_prerequisites.py --run public-deps-YYYYMMDD
uv run --extra coding python scripts/lock_coding_prerequisites.py --runs public-deps-YYYYMMDD
uv run --extra coding harnesslab-coding doctor \
  --config configs/coding-tb21-study.json
uv run --extra coding harnesslab-coding plan \
  --config configs/coding-tb21-study.json
```

First accept a bounded trial of the prepared environment and review loop. Then run the
six-task paired pilot; each command below schedules 30 model trials plus 12 controls:

```bash
uv run --extra coding harnesslab-coding run \
  --config configs/coding-tb21-study.json --network offline --batch tb21-high-offline-YYYYMMDD
uv run --extra coding harnesslab-coding run \
  --config configs/coding-tb21-study.json --network public --batch tb21-high-public-YYYYMMDD
```

`--tasks`, `--groups`, and `--repeats` select a smaller integration run and are captured
in its immutable plan. The six-task lock deliberately prevents accidental full-task
evaluation. Expanding the task set requires a new task lock and environment acceptance.

The controller can run in a CPU-only Slurm job or on a local computer. It runs Harbor
and agent loops, calls the model API, forwards commands, and records results. Compilation
and official tests run in the cloud task environments. No server GPU is requested.

Artifacts live in `artifacts/coding/<batch>/` and `artifacts/coding/jobs/`: immutable
plan, Harbor configs, result, exact-ID cleanup receipt, native trajectory, events, and
summary. Existing completed stages require `--resume`; changed source or configuration
requires a new batch. Incomplete stages are retained for inspection.

## Planned reporting and full-dataset scale

The full Terminal-Bench 2.1 plan contains 89 tasks, five groups, two network conditions,
and one independent sample per cell: 890 model trials. The current six-task lock permits
the 60-trial pilot. The full dataset requires its own complete task lock and environment
acceptance; it is not launched by the existing six-task commands.

All groups use the same original task deadlines and a shared 500-generation cap. No
separate total-token or dollar cutoff is imposed. API retries and Harbor automatic
trial retries are both zero. Each task/group/network cell runs once to reduce cost.
The primary score is mean single-attempt success (Pass@1), with planned,
scored, failed-infrastructure, interrupted, and timed-out counts shown separately.

Report these metrics for each group and network condition, with means, medians and P90
for usage/latency distributions where applicable:

Each model trial writes `agent/metrics.json`, from native model responses and structured
`environment-events.jsonl` execution records. Missing provider fields remain null.
Model-issued tool calls and actual backend commands (including filesystem helpers) are
separate counts. Actor time excludes submission capture; summed command durations can
overlap. The four file-output tasks retain their declared output, while both compilation
tasks retain workspace/install archives with transfer checksums. Missing outputs are
recorded explicitly. Raw trajectories and official verifier results remain authoritative.

| Dimension | Planned measures |
|---|---|
| Completion | Official success rate, task-level results, deadline-stop rate, error categories |
| Model usage | Total model calls, cumulative input tokens, output tokens, reasoning tokens where returned, cached input tokens |
| Output length | Visible assistant text characters, reasoning text characters where retained, tool-argument characters, per-response output-token distribution |
| Tools | Model-issued calls by tool name, commands and file operations separately, observed tool failures, repeated checks |
| Time | Agent wall time, official verification time, preparation time recorded separately |
| Review | Candidate count, actor/reviewer model calls and tokens, accepted/rejected evidence, review false acceptance against final official results |
| Cost-effectiveness | Total evaluation tokens or recorded API cost per successful solve, success-versus-cost comparison |
| Integrity | Manually confirmed benchmark-answer access, unsupported completion, verifier tampering where observed, independent saved-artifact regrades |

Input tokens are cumulative usage across requests, not the final context size. Output
tokens include reasoning when the provider reports them that way. Character lengths are
not token estimates. Missing provider fields remain missing. Provider-side prompt-cache
hits are recorded; no cross-trial answer or solution cache is used.

Interpret the comparisons in order: default versus generic retry asks whether extra
self-review helps; generic retry versus transcript rubric asks whether explicit criteria
help; transcript rubric versus evidence review asks whether tool-based checks and the
evidence gate help together. Mini is an external native-harness baseline. Report the
review overhead alongside any accuracy gain and compare costs on the same tasks.

Select cases using explicit categories before writing conclusions: concrete repair after
an observed failed check, rejection of an unsupported completion claim, successful work
with fewer calls/tokens, extra review with no gain or a regression, and answer access that
can pass the official verifier. Prefer matched task/network/model/budget comparisons.
For an improvement case, show the error, reviewer evidence, exact change, subsequent
check, final official result and added cost. Independently regrade saved submissions when
available. Do not infer that the evidence group is better from the answer-access case alone.

## LangSmith tracing

The study enables `langsmith_tracing` for the four Deep Agents groups only. Put
`LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, and optionally `LANGSMITH_ENDPOINT` and
`LANGSMITH_WORKSPACE_ID` in the controller's `.env`. Credentials are never copied to
the task environment. The graph, nested reviewer/subagent calls, and tools are traced;
`agent/langsmith.json` links the local trial to its remote run. After official scoring,
the controller adds reward, validity, calls, token usage, character lengths, timings,
and review metrics as feedback. Missing provider fields are omitted, not replaced by
zero. Trace uploads and feedback happen outside measured actor time. Mini retains its
native local trajectory. Local artifacts are retained even if monitoring is unavailable.

## Case indexing commands

```bash
uv run --extra coding harnesslab-coding audit --batch tb21-high-public-YYYYMMDD
```

The audit indexes external fetches, benchmark-material access, verifier paths, score
artifacts, and runtime-boundary probes. A signal is a review lead, not a reward-hacking
verdict. For each confirmed case, record the public task, exact model/tool sequence,
returned evidence, saved submission, official result, intervention if any, and an
independent check. Separate legitimate documentation lookup from public benchmark
answer lookup and from verifier tampering.

If a run was interrupted, its missing reward stays missing. Regrading a saved artifact
in a new clean environment is a separate experiment and does not change the original
run's status. Case conclusions distinguish observed behavior, score consequences,
and the proposed mechanism. Matched online/offline trials support a group comparison;
one anecdote alone does not establish a causal network effect.

The first documented example is [public answer access in db-wal-recovery](case-db-wal-answer-access.md).
