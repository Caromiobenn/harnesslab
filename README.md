# HarnessLab

HarnessLab is a reproducible evaluation and diagnostics platform for long-horizon,
tool-using agents. It treats the agent harness—not just the model—as an experimental
variable and asks whether planning, delegation, context management, and verification make
agents more reliable enough to justify their cost.

This is an independent project built with LangChain, LangGraph, and Deep Agents. The
Datawhale tutorials are learning references, not the repository skeleton.

## Why this project exists

An agent reaching the end of its graph is not evidence that the task succeeded. HarnessLab
keeps execution and evaluation on separate data paths:

```text
Public task ──> Harness ──> Model / tools ──> Submission + trace + usage
                                                    │
Private oracle + deterministic validators ─────────┘──> Verdict
```

Only the public task view crosses the harness boundary. Expected answers, hidden checks,
and validator definitions remain evaluator-only. This makes it possible to measure task
success, false completion, recovery, and cost without asking the agent to grade itself.

## Current evidence-backed status

The repository currently provides two distinct layers:

| Layer | Purpose | What it proves |
|---|---|---|
| v0.1 offline contract suite | Mock and scripted model runs through real framework graphs | Adapters, tools, traces, validators, and artifacts are wired correctly |
| v0.2 benchmark protocol | Public/private task packages and OpenAI-compatible execution | Real models can be evaluated without receiving oracle fields |

Implemented harness adapters:

- `langchain_baseline`: minimal `create_agent()` baseline;
- `langchain_planning`: the same baseline plus `TodoListMiddleware`;
- `deepagents_default`: the pinned Deep Agents default bundle;
- `mock`: infrastructure-only deterministic smoke path.

Implemented v0.2 benchmark cases:

- contact normalization and deduplication;
- invoice reconciliation with explicit decimal rounding rules;
- sales rollup over an isolated multi-file workspace.

All three cases have public contracts, separate private evaluation files, independent
deterministic implementations, and mutation tests. They are the first vertical slice, not
yet a benchmark large enough for behavioral claims.

## First self-hosted result

The first exploratory matrix is complete on Qwen2.5-14B-Instruct-AWQ: 3 tasks × 3 harnesses
× 3 repeats = 27 runs, with all 9 paired cells present. The minimal baseline passed 0/9,
explicit planning passed 3/9, and the Deep Agents default bundle passed 0/9. All planning
successes came from one invoice task; its file-task runs ended in execution errors. These
numbers demonstrate the evaluation pipeline and expose distinct failure modes, but the
three-task sample is too small for a general harness ranking.

Read the evidence and claim boundary in
[`docs/experiment-results-20260917.md`](docs/experiment-results-20260917.md). A compact,
machine-readable snapshot lives in
[`results/qwen2.5-14b-awq-20260917/summary.yaml`](results/qwen2.5-14b-awq-20260917/summary.yaml).

The Deep Agents default is deliberately labeled a **bundle**, not a single-agent baseline:
Deep Agents 0.7.x supplies a general-purpose subagent and other middleware by default.
Comparing it with the minimal baseline measures the bundle as a whole and cannot isolate a
single mechanism.

## Quick start

Prerequisites: Linux/WSL and `uv`. The project pins Python 3.12 and Deep Agents 0.7.x.

```bash
uv sync
uv run ruff format --check .
uv run ruff check .
uv run pytest --cov=harnesslab --cov-report=term-missing
```

Run all API-free vertical slices:

```bash
uv run harnesslab run configs/smoke.yaml --fail-on-validation
uv run harnesslab run configs/offline-baseline.yaml --fail-on-validation
uv run harnesslab run configs/offline-planning.yaml --fail-on-validation
uv run harnesslab run configs/offline-deepagents.yaml --fail-on-validation
```

Validate the private references and validator implementations:

```bash
uv run harnesslab verify-benchmark benchmarks/catalog-v0.2.yaml
```

These commands do not require an API key or GPU. The scripted framework runs are contract
tests; their 100% pass rate is not an agent-quality result.

## Running a real model

`run-benchmark` supports any chat-completions endpoint compatible with the OpenAI API, such
as a local vLLM server or an authorized provider endpoint. Copy and edit the example:

```bash
cp configs/benchmark-openai-compatible.example.yaml configs/benchmark-local.yaml
uv run harnesslab run-benchmark configs/benchmark-local.yaml --fail-on-validation
```

For a local server that ignores authentication, keep `api_key_env: null`. For a provider,
set `api_key_env` to the name of an environment variable and export the secret outside the
repository. Inline API keys are not accepted by the schema.

The online adapter currently enforces or records:

- per-task actor model-call limits;
- provider request timeout plus an outer wall-clock deadline on WSL/Linux;
- seed forwarding and sampling settings;
- model/tool lifecycle events without raw prompt or tool payloads;
- input/output tokens and optional configured token pricing;
- execution errors separately from validator failures.

The server experiment matrix is defined in `configs/server-qwen2.5-14b-*.yaml`. Deployment,
model pinning, smoke requirements, and exact replay commands are documented in
[`docs/server-reproduction.md`](docs/server-reproduction.md). Generated real-model artifacts
remain ignored by Git and are interpreted as exploratory until the task suite reaches the
preregistered breadth.

## Reproducible artifacts

Every experiment creates an immutable directory under `artifacts/` containing:

- `manifest.json`: configuration, dependency versions, hashes, seeds, and selected tasks;
- `events.jsonl`: append-only model/tool/run lifecycle events;
- `runs.jsonl`: output, external evaluation, diagnostics, usage, and errors per run;
- `summary.json`: aggregate success, validation-failure, and execution-error counts.

Rebuild a cross-harness comparison directly from raw run records:

```bash
uv run harnesslab summarize-benchmark artifacts/server \
  --output artifacts/server/comparison.json
```

Generated artifacts and secrets are ignored by Git. Benchmark manifests contain hashes and
paths for public and private definitions; private evaluation content never enters the agent
request.

## Repository layout

```text
benchmarks/
  public/                 agent-visible v0.2 task definitions
  private/                evaluator-only oracle and validator definitions
configs/                  offline and OpenAI-compatible experiments
docs/
  learning/               original Chinese learning chapters
src/harnesslab/
  harnesses/              framework and provider adapters
  tools/                  deterministic tools and later domain registries
  validators/             external deterministic evaluators
  benchmark.py            v0.2 public/private schemas
  benchmark_runner.py     bounded online experiment orchestration
  runner.py               v0.1 offline contract orchestration
tests/                    unit, contract, isolation, and integration tests
```

## Evaluation principles

- Agent completion is not task success; external validators own the final verdict.
- Public task data and private oracle data have separate schemas and files.
- Deterministic evidence is preferred whenever a task can be checked without an LLM judge.
- Harness mechanisms are reported as explicit treatments or bundles, never inferred from a
  marketing label.
- Reliability is analyzed with calls, tokens, latency, and cost—not success rate alone.
- Scripted tests and real-model behavioral experiments are reported separately.
- Results are not promoted to benchmark claims until artifacts are reproducible and the task
  set is large enough for the stated conclusion.

## Roadmap and claim boundary

The Qwen3.5 runtime-feedback study adds generic revision, transcript-only rubric grading,
and rubric grading with read-only evidence tools. Its frozen protocol, budget ceilings,
development/holdout split, and claim boundaries are documented in
[`docs/rubric-study-20261025.md`](docs/rubric-study-20261025.md). Implementation and contract
tests do not establish a behavioral improvement; that requires the recorded real-model runs.

- Expand v0.2 to structured, file, code, tool-state, long-horizon, and travel task families.
- Expand the existing isolated workspace and text-tool registry to more task families.
- Implement matched specialist-subagent and verified-execution treatments.
- Add controlled timeout, pagination, schema-change, stale-read, and idempotency faults.
- Run paired multi-model experiments with task-family bootstrap intervals and Pareto analysis.
- Audit an LLM judge against human labels and deterministic ground truth.
- Publish a technical report, failure atlas, dashboard, and result-backed resume bullets.

Until those runs exist, this repository supports claims about evaluation architecture and
framework contracts—not claims that one harness improves agent quality.

## Learning material

The project includes original Chinese chapters designed for understanding and interviews:

1. [From Agent demo to harness evaluation](docs/learning/01-harness-evaluation.md)
2. [Tasks, oracles, and the invisible acceptance boundary](docs/learning/02-task-oracle-design.md)
3. [Harness ablations and causal attribution](docs/learning/03-causal-ablation.md)
4. [Failure analysis: from a red result to a repairable mechanism](docs/learning/04-failure-analysis.md)

Upstream versions and compatibility decisions are documented in
[docs/upstream-compatibility.md](docs/upstream-compatibility.md). The preregistration draft
for future behavioral runs is [docs/experiment-protocol.md](docs/experiment-protocol.md), and
the self-hosted GPU procedure is [docs/server-reproduction.md](docs/server-reproduction.md).
