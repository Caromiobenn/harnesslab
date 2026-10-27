#!/usr/bin/env bash
set -euo pipefail
ROOT=${HARNESSLAB_DATA_ROOT:-/mnt/harnesslab-data}
PROJECT="$ROOT/harnesslab"
exec > >(tee -a "$ROOT/logs/study-preparation.log") 2>&1
trap 'echo "$(date -u +%FT%TZ) PREPARATION_FAILED line=$LINENO"' ERR
cd "$PROJECT"
echo "$(date -u +%FT%TZ) WAITING_FOR_DOWNLOAD_AND_INSTALL"
for dependency_pid in "${HARNESSLAB_INSTALL_PID:-}" "${HARNESSLAB_DOWNLOAD_PID:-}"; do
  if [ -n "$dependency_pid" ]; then
    while kill -0 "$dependency_pid" 2>/dev/null; do sleep 10; done
  fi
done
"$ROOT/inference-env/bin/python" -c 'import torch,vllm; print(torch.__version__,vllm.__version__); assert torch.cuda.is_available(); print(torch.cuda.get_device_name()); print(torch.cuda.get_device_capability())' \
  | tee "$ROOT/runtime/inference-versions.txt"
"$ROOT/bin/uv" pip freeze --python "$ROOT/inference-env/bin/python" > "$ROOT/runtime/inference-requirements.txt"
# The original transfer may finish under system Python 3.10: verify again under 3.12.
.venv/bin/python scripts/server/download_qwen35.py
.venv/bin/python -m ruff format --check .
.venv/bin/python -m ruff check .
.venv/bin/python -m pytest -q
.venv/bin/python -m harnesslab run configs/smoke.yaml
.venv/bin/python -m harnesslab verify-benchmark benchmarks/rubric-v1/dev.yaml
.venv/bin/python -m harnesslab verify-benchmark benchmarks/rubric-v1/holdout.yaml
echo "$(date -u +%FT%TZ) STARTING_INFERENCE"
bash scripts/server/serve-qwen35-9b.sh > "$ROOT/logs/vllm-qwen35.log" 2>&1 &
server_pid=$!
echo "$server_pid" > "$ROOT/runtime/vllm-qwen35.pid"
ready=0
for _ in $(seq 1 180); do
  if curl -sf http://127.0.0.1:8000/health >/dev/null; then ready=1; break; fi
  if ! kill -0 "$server_pid" 2>/dev/null; then tail -80 "$ROOT/logs/vllm-qwen35.log"; exit 1; fi
  sleep 5
done
test "$ready" = 1
.venv/bin/python scripts/server/smoke_qwen35.py
echo "$(date -u +%FT%TZ) RUNNING_DEVELOPMENT_MATRIX"
.venv/bin/python scripts/run_rubric_matrix.py --split dev --repeats 1 --output "$ROOT/artifacts/rubric-dev-v1"
.venv/bin/python scripts/analyze_rubric_matrix.py "$ROOT/artifacts/rubric-dev-v1"
echo "$(date -u +%FT%TZ) DEVELOPMENT_FINISHED_READY_FOR_REVIEW"
