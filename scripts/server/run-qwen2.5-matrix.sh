#!/usr/bin/env bash
set -euo pipefail

project_dir="${HARNESSLAB_PROJECT_DIR:-/mnt/harnesslab-data/harnesslab}"
artifact_dir="${HARNESSLAB_ARTIFACT_DIR:-/mnt/harnesslab-data/artifacts/server}"
python_bin="${HARNESSLAB_PYTHON:-${project_dir}/.venv/bin/python}"

export NO_PROXY="127.0.0.1,localhost"
export no_proxy="127.0.0.1,localhost"

curl --fail --silent --show-error http://127.0.0.1:8000/health >/dev/null
mkdir -p "${artifact_dir}"
cd "${project_dir}"

failed_conditions=0
for config in \
  configs/server-qwen2.5-14b-baseline.yaml \
  configs/server-qwen2.5-14b-planning.yaml \
  configs/server-qwen2.5-14b-deepagents.yaml
do
  if ! "${python_bin}" -m harnesslab run-benchmark "${config}" --output-dir "${artifact_dir}"
  then
    failed_conditions=$((failed_conditions + 1))
  fi
done

summary_path="${artifact_dir}/comparison-$(date -u +%Y%m%dT%H%M%SZ).json"
"${python_bin}" -m harnesslab summarize-benchmark "${artifact_dir}" --output "${summary_path}"

if ((failed_conditions > 0)); then
  echo "${failed_conditions} condition(s) contained execution errors; artifacts and comparison were retained." >&2
  exit 1
fi
