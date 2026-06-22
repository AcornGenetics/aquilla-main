#!/usr/bin/env bash
# Mid-run update guard for the fleet cutover (#188, ADR-002).
#
# Refuses to let the fleet updater recreate containers while a PCR run is in
# progress (which would kill the run). Polls the device backend /health and:
#
#   exit 0  -> idle, safe to update
#   exit 3  -> a run is in progress, defer this device
#   exit 2  -> backend unreachable; run state can't be confirmed (fail-closed)
#
# Override with --force (e.g. a genuinely dead backend that must be updated).
#
# Configurable via HEALTH_URL (default http://localhost:8090/health) so the
# behavior can be exercised against a stub endpoint.
set -uo pipefail

HEALTH_URL="${HEALTH_URL:-http://localhost:8090/health}"

FORCE=0
for arg in "$@"; do
    case "$arg" in
        --force) FORCE=1 ;;
    esac
done

if [[ "$FORCE" -eq 1 ]]; then
    echo "run_guard: --force given, skipping mid-run check"
    exit 0
fi

body=$(curl -fsS --max-time 5 "$HEALTH_URL" 2>/dev/null)
if [[ $? -ne 0 || -z "$body" ]]; then
    echo "run_guard: cannot reach backend at ${HEALTH_URL} to confirm run state" \
         "— refusing update (use --force to override)" >&2
    exit 2
fi

if echo "$body" | grep -qE '"run_in_progress"[[:space:]]*:[[:space:]]*true'; then
    echo "run_guard: a PCR run is in progress — deferring update" \
         "(use --force to override)" >&2
    exit 3
fi

echo "run_guard: device idle — safe to update"
exit 0
