#!/usr/bin/env bash
set -euo pipefail

model_dir="${HARNESSLAB_MODEL_DIR:-/mnt/harnesslab-data/models/Qwen2.5-14B-Instruct-AWQ}"
runtime_dir="${HARNESSLAB_RUNTIME_DIR:-/mnt/harnesslab-data/runtime}"
python_bin="${VLLM_PYTHON:-/home/ubuntu/miniforge3/bin/python}"

test -f "${model_dir}/config.json"
mkdir -p "${runtime_dir}"

export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
export NO_PROXY="127.0.0.1,localhost"
export no_proxy="127.0.0.1,localhost"

exec "${python_bin}" -m vllm.entrypoints.openai.api_server \
  --host 127.0.0.1 \
  --port 8000 \
  --model "${model_dir}" \
  --served-model-name qwen2.5-14b-instruct-awq \
  --quantization awq \
  --dtype half \
  --max-model-len 16384 \
  --gpu-memory-utilization 0.90 \
  --enable-auto-tool-choice \
  --tool-call-parser hermes
