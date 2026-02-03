#!/usr/bin/env bash
# Usage: ./run_optics_detection.sh <path-to-optics-log>
# Runs aq_curve detection on an optics log and writes a results JSON.

set -euo pipefail

LOG_PATH=${1:-}

if [[ -z "$LOG_PATH" ]]; then
  echo "Usage: $0 <path-to-optics-log>" >&2
  exit 1
fi

if [[ ! -f "$LOG_PATH" ]]; then
  echo "Log file not found: $LOG_PATH" >&2
  exit 1
fi

# Activate local venv if present
if [[ -f ".venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

mkdir -p logs/results

OUTPUT_JSON="logs/results/$(basename "${LOG_PATH%.*}").json"

python -c "from aq_curve.curve import Curve; Curve().results_to_json('${LOG_PATH}','${OUTPUT_JSON}')"
echo "Wrote results JSON -> ${OUTPUT_JSON}"

python - <<PY
import json

with open("${OUTPUT_JSON}") as f:
    data = json.load(f)

rows = [("ROX", "2"), ("FAM", "1")]
for label, key in rows:
    row = data.get(key, {})
    values = [row.get(str(well), "Not Detected") for well in range(1, 5)]
    summary = ", ".join(values)
    print(f"{label}: {summary}")
PY
