#!/usr/bin/env bash
set -euo pipefail
ROOT=${HARNESSLAB_DATA_ROOT:-/mnt/harnesslab-data}
MODEL="$ROOT/models/Qwen3.5-9B"
REV=c202236235762e1c871ad0ccb60c8ee5ba337b9a
mkdir -p "$MODEL"
for name in config.json tokenizer.json tokenizer_config.json chat_template.jinja merges.txt vocab.json model.safetensors.index.json preprocessor_config.json video_preprocessor_config.json model.safetensors-00001-of-00004.safetensors model.safetensors-00002-of-00004.safetensors model.safetensors-00003-of-00004.safetensors model.safetensors-00004-of-00004.safetensors; do
  echo "$(date -u +%FT%TZ) $name"
  curl -4 -fL --retry 5 --retry-delay 5 --connect-timeout 20 --continue-at - \
    "https://hf-mirror.com/Qwen/Qwen3.5-9B/resolve/$REV/$name?download=true" -o "$MODEL/$name"
done
printf '%s\n' "$REV" > "$MODEL/REVISION"
(cd "$MODEL" && sha256sum *.json *.safetensors *.jinja merges.txt vocab.json > SHA256SUMS)
