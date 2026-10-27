#!/usr/bin/env bash
set -euo pipefail
ROOT=${HARNESSLAB_DATA_ROOT:-/mnt/harnesslab-data}
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export HF_HOME="$ROOT/cache/huggingface"
export VLLM_WORKER_MULTIPROC_METHOD=spawn
export CUDA_VISIBLE_DEVICES=0
exec "$ROOT/inference-env/bin/vllm" serve "$ROOT/models/Qwen3.5-9B" \
  --served-model-name Qwen3.5-9B --host 127.0.0.1 --port 8000 \
  --tensor-parallel-size 1 --dtype bfloat16 --language-model-only \
  --max-model-len 32768 --max-num-seqs 1 --gpu-memory-utilization 0.88 \
  --enforce-eager --enable-auto-tool-choice --tool-call-parser qwen3_xml \
  --reasoning-parser qwen3 --generation-config vllm
