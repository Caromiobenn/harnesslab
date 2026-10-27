#!/usr/bin/env bash
set -euo pipefail
ROOT=${HARNESSLAB_DATA_ROOT:-/mnt/harnesslab-data}
cd "$ROOT/harnesslab"
exec > >(tee -a "$ROOT/logs/final-study.log") 2>&1
trap 'echo "$(date -u +%FT%TZ) STUDY_FAILED line=$LINENO"' ERR
echo "$(date -u +%FT%TZ) WAITING_FOR_DEVELOPMENT"
if [ -n "${HARNESSLAB_DEV_PID:-}" ]; then
  while kill -0 "$HARNESSLAB_DEV_PID" 2>/dev/null; do sleep 10; done
fi
.venv/bin/python scripts/analyze_rubric_matrix.py "$ROOT/artifacts/rubric-dev-v2"
.venv/bin/python - <<'PY'
import json
from pathlib import Path
root = Path('/mnt/harnesslab-data/artifacts/rubric-dev-v2')
d = json.loads((root / 'analysis.json').read_text())
assert d['complete'] and d['completed'] == 24
assert set(d['arms']) == {'default', 'generic_retry', 'rubric_transcript', 'rubric_evidence'}
assert all(v['runs'] == 6 for v in d['arms'].values())
for row in map(json.loads, (root / 'progress.jsonl').read_text().splitlines()):
    r = json.loads((Path(row['artifact_directory']) / 'runs.jsonl').read_text())
    roles = r['diagnostics'].get('role_usage', {})
    if roles:
        for key in ['model_calls', 'input_tokens', 'output_tokens']:
            assert r['metrics'][key] == sum(v[key] for v in roles.values()), (row, key)
print('DEVELOPMENT_COVERAGE_AND_USAGE_VERIFIED', flush=True)
PY
echo "$(date -u +%FT%TZ) STARTING_GRADER_CALIBRATION"
.venv/bin/python scripts/calibrate_rubric_grader.py --output "$ROOT/artifacts/rubric-calibration-v2"
echo "$(date -u +%FT%TZ) STARTING_FROZEN_HOLDOUT"
.venv/bin/python scripts/run_rubric_matrix.py --split holdout --repeats 3 --output "$ROOT/artifacts/rubric-holdout-v2"
.venv/bin/python scripts/analyze_rubric_matrix.py "$ROOT/artifacts/rubric-holdout-v2"
.venv/bin/python - <<'PY'
import json
from pathlib import Path
root = Path('/mnt/harnesslab-data')
d = json.loads((root / 'artifacts/rubric-holdout-v2/analysis.json').read_text())
c = json.loads((root / 'artifacts/rubric-calibration-v2/summary.json').read_text())
assert d['complete'] and d['completed'] == 216
assert all(v['runs'] == 54 for v in d['arms'].values())
assert c['complete'] and sum(v['runs'] for v in c['groups'].values()) == 60
(root / 'runtime/rubric-study-complete.json').write_text(json.dumps({
    'complete': True, 'development_runs': 24, 'calibration_runs': 60, 'holdout_runs': 216
}, indent=2))
print('FROZEN_STUDY_COMPLETE_REPORT_READY', flush=True)
PY
