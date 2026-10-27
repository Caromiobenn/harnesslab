#!/usr/bin/env bash
set -euo pipefail
ROOT=${HARNESSLAB_DATA_ROOT:-/mnt/harnesslab-data}
export UV_CACHE_DIR="$ROOT/cache/uv"
export UV_PYTHON_INSTALL_DIR="$ROOT/python"
export TMPDIR="$ROOT/cache/tmp"
UV="$ROOT/bin/uv"
mkdir -p "$ROOT"/{logs,runtime,models,cache/tmp}
"$UV" venv --python 3.12 "$ROOT/inference-env"
"$UV" pip install --python "$ROOT/inference-env/bin/python" --no-cache \
  --index-url https://pypi.tuna.tsinghua.edu.cn/simple 'vllm==0.32.0' \
  > "$ROOT/logs/vllm-install.log" 2>&1
"$ROOT/inference-env/bin/python" -c 'import torch,vllm; print(torch.__version__,vllm.__version__); print(torch.cuda.get_device_name()); print(torch.cuda.get_device_capability())' \
  > "$ROOT/runtime/inference-versions.txt"
"$UV" pip freeze --python "$ROOT/inference-env/bin/python" > "$ROOT/runtime/inference-requirements.txt"
