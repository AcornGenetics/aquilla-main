#!/usr/bin/env bash
# Image retention / rollback logic for a Sentri (issue #355).
#
# Nothing on a device has ever removed an image. Measured on sn03: 30 images,
# ~9.8 GB reclaimable, the oldest being a telemetry image from 2023 belonging to
# a stack replaced by Grafana Alloy.
#
# A device keeps at most TWO sets, both from its CURRENT ring:
#
#     current   the image it is running   (carries the ring tag)
#     fallback  the build it replaced     (untagged)
#
# A "set" is one API image plus its matching UI image, so at most 4 Aquila
# images on disk.
#
# ── The two cases ─────────────────────────────────────────────────────────────
#
# SAME-RING UPDATE (pilot v2 -> pilot v3)
#     The replaced build becomes the fallback; the previous fallback is deleted.
#     current=v3, fallback=v2, v1 removed.
#
# RING CHANGE (pilot -> prod)
#     Every image from the old ring goes, current and fallback alike, and the
#     device starts with NO fallback. Falling back across rings is not a
#     rollback: promotion flows sandbox -> dev -> pilot -> prod, so the old
#     ring's image is newer and *less* soaked than the one just promoted in.
#
# ── Why one ring name is the only state needed ────────────────────────────────
#
# An untagged image carries no record of its ring -- verified on-device, an
# orphan has RepoTags: [], RepoDigests: [], Labels: map[]. So "the previous
# pilot image" is not identifiable by inspection.
#
# The ring-change rule removes the need to identify it. Because a ring change
# deletes every old-ring image, the invariant afterwards is zero orphans. Each
# same-ring update then adds exactly one and removes the previous, so the orphan
# pool is always <= 1 AND always from the current ring. Sorting by date is
# therefore exact, not an approximation -- provided we know whether the ring
# changed, which is the one thing recorded in STATE_FILE.
#
# ── Safety ────────────────────────────────────────────────────────────────────
#   - An image a container references is never removed. Docker enforces this
#     (`docker rmi` refuses), not this script, so a logic error here cannot take
#     down a running container.
#   - Anything not positively identified as an Aquila API or UI image is never
#     touched: Watchtower and any future image are never candidates.
#   - If the ring cannot be determined, the script exits without removing
#     anything rather than guessing.
#
# Env:
#   DEVICE_RING  override the detected ring (default: IMAGE_TAG from the .env files)
#   STATE_FILE   where the last-seen ring is recorded
#   DRY_RUN      set to 1 to report without removing
set -euo pipefail

DRY_RUN="${DRY_RUN:-0}"
FLEET_ENV="${FLEET_ENV:-/opt/fleet/.env}"
DEVICE_ENV="${DEVICE_ENV:-/opt/aquila/config/device.env}"
STATE_FILE="${STATE_FILE:-/opt/fleet/.prune-state}"

KNOWN_RINGS="sandbox dev pilot prod"
# `latest` is not a ring: it tracks whatever was built last and no device should
# be running it, so it is always removable.
NON_RING_TAGS="latest"

log() { printf '[prune-images] %s\n' "$*"; }

command -v docker >/dev/null 2>&1 || { log "docker not found; nothing to do"; exit 0; }

_detect_ring() {
    local f v
    for f in "${FLEET_ENV}" "${DEVICE_ENV}"; do
        [[ -r "${f}" ]] || continue
        v="$(grep -E '^IMAGE_TAG=' "${f}" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"'\''[:space:]')"
        if [[ -n "${v}" ]]; then printf '%s' "${v}"; return; fi
    done
}

RING="${DEVICE_RING:-$(_detect_ring)}"
if [[ -z "${RING}" ]]; then
    log "ring unknown (no IMAGE_TAG in ${FLEET_ENV} or ${DEVICE_ENV})"
    log "refusing to remove anything — will not guess"
    exit 0
fi

LAST_RING=""
[[ -r "${STATE_FILE}" ]] && LAST_RING="$(cat "${STATE_FILE}" 2>/dev/null | tr -d '[:space:]')"

# No state means either a fresh device or the first run on an existing one. Treat
# it as a ring change: an unverifiable fallback is not a fallback, and this
# establishes the zero-orphan invariant everything below relies on. Costs at most
# one rollback target, once.
if [[ -z "${LAST_RING}" ]]; then
    MODE="ring-change"
    log "ring: ${RING} (no previous state — treating as a ring change to establish a clean baseline)"
elif [[ "${LAST_RING}" != "${RING}" ]]; then
    MODE="ring-change"
    log "ring changed: ${LAST_RING} -> ${RING} (all ${LAST_RING} images will be removed, no fallback)"
else
    MODE="same-ring"
    log "ring: ${RING} (unchanged — keeping current + 1 fallback)"
fi

_rmi() {
    local ref="$1"
    if [[ "${DRY_RUN}" == "1" ]]; then
        log "  would remove ${ref}"
        return
    fi
    if docker rmi "${ref}" >/dev/null 2>&1; then
        log "  removed ${ref}"
    else
        log "  skipped ${ref} (in use or has children)"
    fi
}

# Untagged images have no repository name, so `docker images` cannot tell an
# orphaned API image from an orphaned UI one. They are classified by config baked
# in at build time, verified on-device:
#   API -> WorkingDir=/opt/aquila, Cmd=[uvicorn aquila_web.main:app ...]
#   UI  -> WorkingDir=/,           Cmd=[nginx -g daemon off;]
# Once #351 bakes OCI labels in, this can key off org.opencontainers.image.*
# and stop depending on the entrypoint.
_classify() {
    local id="$1" workdir cmd
    workdir="$(docker inspect "${id}" --format '{{.Config.WorkingDir}}' 2>/dev/null || true)"
    cmd="$(docker inspect "${id}" --format '{{json .Config.Cmd}}' 2>/dev/null || true)"
    if [[ "${workdir}" == "/opt/aquila" ]]; then echo api
    elif [[ "${cmd}" == *nginx* ]];           then echo ui
    else                                           echo other
    fi
}

# ── Step 1: fallbacks (untagged Aquila images) ────────────────────────────────
# ring-change keeps none; same-ring keeps the newest of each family.
keep_n=0
[[ "${MODE}" == "same-ring" ]] && keep_n=1

for family in api ui; do
    candidates="$(
        docker images --filter dangling=true --quiet 2>/dev/null | sort -u | while read -r id; do
            [[ -n "${id}" ]] || continue
            [[ "$(_classify "${id}")" == "${family}" ]] || continue
            printf '%s %s\n' "$(docker inspect "${id}" --format '{{.Created}}' 2>/dev/null)" "${id}"
        done | sort -r | awk '{ print $2 }'
    )"
    [[ -n "${candidates}" ]] || { log "${family}: no fallback images"; continue; }

    total="$(printf '%s\n' "${candidates}" | wc -l | tr -d ' ')"
    stale="$(printf '%s\n' "${candidates}" | tail -n "+$(( keep_n + 1 ))")"
    [[ -n "${stale}" ]] || { log "${family}: ${total} fallback, keeping it"; continue; }

    log "${family}: ${total} untagged, keeping ${keep_n}, removing $(printf '%s\n' "${stale}" | wc -l | tr -d ' ')"
    printf '%s\n' "${stale}" | while read -r id; do
        [[ -n "${id}" ]] || continue
        _rmi "${id}"
    done
done

# ── Step 2: tagged images from other rings ────────────────────────────────────
# Runs after step 1 deliberately. Removing a tag turns that image into an orphan,
# so doing this first would let a just-untagged foreign-ring image compete to be
# kept as the fallback.
for tag in ${KNOWN_RINGS} ${NON_RING_TAGS}; do
    [[ "${tag}" == "${RING}" ]] && continue
    while read -r ref; do
        [[ -n "${ref}" ]] || continue
        _rmi "${ref}"
    done < <(docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null \
             | grep -E "aquilla-main-(api|ui):${tag}$" || true)
done

if [[ "${DRY_RUN}" == "1" ]]; then
    log "dry run complete (ring=${RING}, mode=${MODE}) — state not written"
else
    if printf '%s\n' "${RING}" > "${STATE_FILE}" 2>/dev/null; then
        log "done (ring=${RING}, mode=${MODE})"
    else
        # Without state every run looks like a ring change, so no fallback is
        # ever kept. Safe, but worth surfacing.
        log "done (ring=${RING}, mode=${MODE}) — WARNING: could not write ${STATE_FILE}"
    fi
fi
