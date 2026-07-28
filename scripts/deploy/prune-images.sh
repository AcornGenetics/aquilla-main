#!/usr/bin/env bash
# Cap the number of Aquila image sets retained on a device (issue #355).
#
# Nothing in any deploy path removes old images. fleet-update.sh runs
# `docker compose pull` + `up -d --force-recreate`, and compose never deletes
# the image it replaced. Watchtower's --cleanup would, but it runs without
# --interval so it only acts on POST /v1/update and mostly never fires.
# The result is unbounded accumulation: sn03 was measured holding 27 images,
# 19 of them dangling, 8.84 GB reclaimable.
#
# A "set" is one API image plus its matching UI image. Retention rules, in
# priority order:
#
#   1. Never remove an image a container references. Enforced by Docker itself
#      -- `docker rmi` refuses, so a logic error here cannot take down a
#      running container.
#   2. Never remove a ring-tagged image (sandbox/dev/pilot/prod). Enforced by
#      construction: only `dangling=true` images are considered, and a ring tag
#      means an image is not dangling. These are deliberate offline rollback
#      targets -- a device holding both api:sandbox and api:dev keeps both.
#   3. Of what remains, keep the most recent (IMAGE_RETENTION_SETS - 1) per
#      family. The running set is tagged, so untagged images are all previous
#      versions.
#   4. Remove the rest.
#
# Anything not positively identified as an Aquila API or UI image is left
# alone, so Watchtower and any future images are never candidates.
#
# Env:
#   IMAGE_RETENTION_SETS  total sets to keep, including the running one (default 3)
#   DRY_RUN               set to 1 to report without removing
set -euo pipefail

RETENTION_SETS="${IMAGE_RETENTION_SETS:-3}"
DRY_RUN="${DRY_RUN:-0}"

log() { printf '[prune-images] %s\n' "$*"; }

if ! [[ "${RETENTION_SETS}" =~ ^[0-9]+$ ]] || (( RETENTION_SETS < 1 )); then
    log "IMAGE_RETENTION_SETS must be a positive integer (got '${RETENTION_SETS}')"
    exit 1
fi

# The running set is tagged, not dangling, so it is never in the candidate list.
KEEP_UNTAGGED=$(( RETENTION_SETS - 1 ))

if ! command -v docker >/dev/null 2>&1; then
    log "docker not found; nothing to do"
    exit 0
fi

# Classify an untagged image using config baked in at build time.
#
# Dangling images have lost their repository name, so `docker images` output
# cannot tell an orphaned API image from an orphaned UI one. These two markers
# were verified on a live device:
#   API -> WorkingDir=/opt/aquila, Cmd=[uvicorn aquila_web.main:app ...]
#   UI  -> WorkingDir=/,           Cmd=[nginx -g daemon off;]
# Once #351 bakes OCI labels into the images, this can key off
# org.opencontainers.image.* instead and stop depending on the entrypoint.
_classify() {
    local id="$1" workdir cmd
    workdir="$(docker inspect "${id}" --format '{{.Config.WorkingDir}}' 2>/dev/null || true)"
    cmd="$(docker inspect "${id}" --format '{{json .Config.Cmd}}' 2>/dev/null || true)"

    if [[ "${workdir}" == "/opt/aquila" ]]; then
        echo api
    elif [[ "${cmd}" == *nginx* ]]; then
        echo ui
    else
        echo other
    fi
}

total_removed=0

for family in api ui; do
    # Untagged images of this family, newest first.
    candidates="$(
        docker images --filter dangling=true --quiet 2>/dev/null | sort -u | while read -r id; do
            [[ -n "${id}" ]] || continue
            [[ "$(_classify "${id}")" == "${family}" ]] || continue
            printf '%s %s\n' "$(docker inspect "${id}" --format '{{.Created}}' 2>/dev/null)" "${id}"
        done | sort -r | awk '{ print $2 }'
    )"

    if [[ -z "${candidates}" ]]; then
        log "${family}: no untagged images"
        continue
    fi

    count="$(printf '%s\n' "${candidates}" | wc -l | tr -d ' ')"
    stale="$(printf '%s\n' "${candidates}" | tail -n "+$(( KEEP_UNTAGGED + 1 ))")"

    if [[ -z "${stale}" ]]; then
        log "${family}: ${count} untagged, keeping all (limit ${KEEP_UNTAGGED})"
        continue
    fi

    stale_count="$(printf '%s\n' "${stale}" | wc -l | tr -d ' ')"
    log "${family}: ${count} untagged, keeping ${KEEP_UNTAGGED} newest, removing ${stale_count}"

    printf '%s\n' "${stale}" | while read -r id; do
        [[ -n "${id}" ]] || continue
        if [[ "${DRY_RUN}" == "1" ]]; then
            log "  would remove ${id}"
            continue
        fi
        # Fails harmlessly when a container still references the image; that is
        # rule 1 being enforced by Docker rather than by this script.
        if docker rmi "${id}" >/dev/null 2>&1; then
            log "  removed ${id}"
        else
            log "  skipped ${id} (in use or has children)"
        fi
    done

    total_removed=$(( total_removed + stale_count ))
done

if [[ "${DRY_RUN}" == "1" ]]; then
    log "dry run complete (IMAGE_RETENTION_SETS=${RETENTION_SETS})"
else
    log "done (IMAGE_RETENTION_SETS=${RETENTION_SETS})"
fi
