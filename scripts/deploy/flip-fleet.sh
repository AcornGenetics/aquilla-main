#!/usr/bin/env bash
# Fleet cutover orchestrator (#188, ADR-016).
#
# Flips devices from the old image namespace to acorngenetics/sentri over
# (Tailscale) SSH. Per device it points GHCR_REPO at the new repo and runs
# fleet-update.sh — whose mid-run guard defers any device with a live PCR run.
#
# SAFE BY DEFAULT: dry-run unless --execute is given. Dry-run prints the plan
# and touches nothing, so this can be reviewed and even run without risk.
#
#   flip-fleet.sh --devices hosts.txt            # dry-run: show the plan
#   flip-fleet.sh --devices hosts.txt --execute  # actually flip the fleet
#
# hosts.txt: one device hostname per line (# comments and blanks ignored).
set -uo pipefail

NEW_GHCR_REPO="${NEW_GHCR_REPO:-acorngenetics/sentri}"
SSH_CMD="${SSH_CMD:-ssh}"

DEVICES_FILE=""
EXECUTE=0
for ((i = 1; i <= $#; i++)); do
    case "${!i}" in
        --devices) j=$((i + 1)); DEVICES_FILE="${!j}" ;;
        --execute) EXECUTE=1 ;;
    esac
done

if [[ -z "$DEVICES_FILE" || ! -f "$DEVICES_FILE" ]]; then
    echo "flip-fleet: --devices FILE is required (one hostname per line)" >&2
    exit 64
fi

# portable read (no mapfile — devices run modern bash, but dev machines may be 3.2)
DEVICES=()
while IFS= read -r line; do
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    DEVICES+=("$line")
done < "$DEVICES_FILE"

if [[ "$EXECUTE" -ne 1 ]]; then
    echo "DRY RUN — would flip ${#DEVICES[@]} device(s) to ${NEW_GHCR_REPO}:"
    for d in "${DEVICES[@]}"; do
        echo "  - ${d}"
    done
    echo "(pass --execute to perform the cutover)"
    exit 0
fi

# --- execute: flip each device over SSH ---
FLEET_ENV_PATH="${FLEET_ENV_PATH:-/opt/fleet/.env}"
FLEET_UPDATE="${FLEET_UPDATE:-/opt/fleet/fleet-update.sh}"
GUARD_DEFER_CODE=3  # run_guard.sh exit code for "a run is in progress"

flipped=(); deferred=(); failed=()
for d in "${DEVICES[@]}"; do
    # point GHCR_REPO at the new repo, then trigger the (guarded) update
    remote="sudo sed -i 's|^GHCR_REPO=.*|GHCR_REPO=${NEW_GHCR_REPO}|' ${FLEET_ENV_PATH} && sudo ${FLEET_UPDATE}"
    if "$SSH_CMD" "$d" "$remote"; then
        flipped+=("$d"); echo "  [ok] ${d}"
    else
        rc=$?
        if [[ "$rc" -eq "$GUARD_DEFER_CODE" ]]; then
            deferred+=("$d"); echo "  [deferred — run in progress] ${d}"
        else
            failed+=("$d"); echo "  [FAILED rc=${rc}] ${d}"
        fi
    fi
done

echo "---"
echo "flipped: ${#flipped[@]}  deferred: ${#deferred[@]}  failed: ${#failed[@]}"
[[ ${#deferred[@]} -gt 0 ]] && echo "deferred (re-run later): ${deferred[*]}"
[[ ${#failed[@]} -gt 0 ]] && echo "failed: ${failed[*]}"

# non-zero if any device still needs attention, so the operator follows up
[[ ${#deferred[@]} -eq 0 && ${#failed[@]} -eq 0 ]] || exit 1
exit 0
