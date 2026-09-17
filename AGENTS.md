# HarnessLab contributor guide

## Required checks

Run these from the repository root after every code change:

```bash
uv run ruff format --check .
uv run ruff check .
uv run pytest
```

Use `uv run harnesslab run configs/smoke.yaml` for the offline end-to-end check.

## Evaluation invariants

- Never infer task success from an agent's final message; validators own the verdict.
- Do not expose `expected` values or validator-only evidence to a real agent adapter.
- Keep task inputs and validators identical across ablation configurations.
- Record errors as run data so one failed task does not erase the rest of an experiment.
- Do not report benchmark improvements until the underlying artifacts are reproducible.

## Safety and reproducibility

- Never commit API keys, SSH credentials, `.env`, or raw private datasets.
- Do not give an agent host shell access in unit tests. Prefer `StateBackend` or an isolated
  temporary workspace.
- Pin supported dependency ranges in `pyproject.toml` and commit `uv.lock` changes.
- Keep generated experiment outputs under `artifacts/`; they are ignored by Git.
