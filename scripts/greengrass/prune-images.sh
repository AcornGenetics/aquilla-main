#!/usr/bin/env bash
# Cap the images a device retains (#397). Runs from the component lifecycle after
# `docker compose up -d`, i.e. exactly when a deployment has superseded an image.
#
# Nothing has ever removed an image from these devices, and Greengrass does not do it
# either: sn01 was measured carrying both its 2026-07-31 and 2026-08-03 ECR images after
# a second deployment, plus 4.85 GB of older dangling layers -- ~7.6 GB reclaimable.
#
# The rule:
#
#     keep any image a container references (running or stopped)
#     keep the newest image per repository
#     delete everything else
#
# Why "newest per repository" rather than the simpler `docker image prune -a`:
#
#   * Greengrass pins images by ECR digest, so a superseded image keeps its repository
#     name and shows tag <none>. Docker does NOT call that dangling, so the built-in
#     `docker image prune -f` leaves it -- and one ~1.25 GB set would accumulate per
#     deployment. Dangling-only cleanup does not solve this problem.
#
#   * `docker image prune -a` would solve it, but also deletes images that are unused
#     only *between* runs. aquila-cert-renew.service starts a throwaway container from
#     ghcr.io/<repo>-api:<tag> once a day; for the other 23h59m that image is unused.
#     Deleting it makes the next certificate renewal depend on a GHCR re-pull, on a
#     device that has migrated to ECR and may no longer hold GHCR credentials. A
#     failure there is silent until the certificate expires and the device drops off
#     the fleet. Keeping the newest per repository protects it without special-casing,
#     and without editing any host file.
#
# Nothing here needs root: ggc_user is in the docker group. That is deliberate -- it
# keeps this shippable without the host-config privilege question that blocks #353/#354.

set -euo pipefail

DRY_RUN="${DRY_RUN:-0}"

log() { echo "prune: $*"; }

# repo_of <ref>
# "reg/name:tag" -> "reg/name" ; "reg/name@sha256:..." -> "reg/name" ; "" -> ""
# Registry-agnostic on purpose: a device migrating from the Watchtower world arrives
# carrying ghcr.io images, and they must be groupable the same way as ECR ones.
repo_of() {
    local ref="${1:-}"
    [[ -z "${ref}" || "${ref}" == "<none>"* ]] && return 0
    ref="${ref%%@*}"          # strip a digest, if any
    # Strip a tag, but not a registry port: only when the last ':' follows the last '/'
    if [[ "${ref##*/}" == *:* ]]; then
        ref="${ref%:*}"
    fi
    printf '%s' "${ref}"
}

# select_removals <protected_ids>
#
# Reads image records on stdin, one per line:
#     <id><TAB><created-rfc3339><TAB><ref>[ <ref>...]
# `created` must sort lexically (RFC3339 UTC does). Refs may be empty for a dangling
# image. Writes the IDs to remove, one per line.
#
# Pure text processing so the decision can be tested without Docker.
# Deliberately avoids bash associative arrays: macOS still ships bash 3.2, where
# `declare -A` silently degrades to an indexed array and subscripts are evaluated as
# arithmetic. The devices run bash 5, but a script nobody can test locally is worse
# than one built from sort/awk, which behave the same everywhere.
select_removals() {
    local protected=" ${1:-} "
    local records id created refs ref repo pairs="" winners

    records="$(cat)"
    [[ -z "${records}" ]] && return 0

    # Flatten to <repo>\t<created>\t<id>, one line per (image, repository) pair. A
    # dangling image contributes none, so it can never win a repository and is always
    # a removal candidate.
    while IFS=$'\t' read -r id created refs; do
        [[ -z "${id}" ]] && continue
        for ref in ${refs}; do
            repo="$(repo_of "${ref}")"
            [[ -z "${repo}" ]] && continue
            pairs="${pairs}${repo}"$'\t'"${created}"$'\t'"${id}"$'\n'
        done
    done <<< "${records}"

    # Newest per repository: sort by repo, then created descending, take the first of
    # each repo. RFC3339 UTC sorts lexically, so this needs no date parsing.
    winners=" $(printf '%s' "${pairs}" \
        | sort -t$'\t' -k1,1 -k2,2r \
        | awk -F'\t' '!seen[$1]++ { printf "%s ", $3 }') "

    while IFS=$'\t' read -r id created refs; do
        [[ -z "${id}" ]] && continue
        [[ "${protected}" == *" ${id} "* ]] && continue
        [[ "${winners}" == *" ${id} "* ]] && continue
        printf '%s\n' "${id}"
    done <<< "${records}"
}

# collect_images -- emit the records select_removals expects, from the local daemon.
collect_images() {
    local ids
    # `docker images --quiet` alone omits dangling images -- measured on sn01 (docker
    # 29.7.0): 11 listed, 9 dangling, 20 in `docker system df`. Those 9 were 4.85 GB of
    # the 5.9 GB reclaimable, i.e. most of the problem. The union is used rather than
    # `--all`, which also surfaces intermediate layers that must never be removed
    # individually.
    ids="$( { docker images --quiet; docker images --filter dangling=true --quiet; } \
        | sort -u )"
    [[ -z "${ids}" ]] && return 0
    # .Created is RFC3339 UTC, which sorts lexically; RepoTags/RepoDigests are absent
    # on a dangling image, leaving the refs field empty.
    # shellcheck disable=SC2086
    docker inspect --format \
        '{{.Id}}{{"\t"}}{{.Created}}{{"\t"}}{{range .RepoTags}}{{.}} {{end}}{{range .RepoDigests}}{{.}} {{end}}' \
        ${ids} 2>/dev/null || true
}

# protected_ids -- image IDs referenced by any container, running or stopped.
# Docker refuses to remove these anyway; listing them keeps the log honest about
# *why* something was kept rather than relying on `docker rmi` to fail.
protected_ids() {
    local containers
    containers="$(docker ps --all --quiet)"
    [[ -z "${containers}" ]] && return 0
    # shellcheck disable=SC2086
    docker inspect --format '{{.Image}}' ${containers} 2>/dev/null | sort -u | tr '\n' ' '
}

main() {
    local records protected removals count=0 removed=0 rmi_err rc

    records="$(collect_images)"
    if [[ -z "${records}" ]]; then
        log "no images on this device — nothing to do"
        return 0
    fi
    count="$(printf '%s\n' "${records}" | grep -c . || true)"
    protected="$(protected_ids)"

    removals="$(printf '%s\n' "${records}" | select_removals "${protected}")"

    if [[ -z "${removals}" ]]; then
        # Distinguish "evaluated images, none were removable" from "found nothing to
        # evaluate". A silent no-op is how a cleanup stops working unnoticed.
        log "${count} images, 0 removable (all in use or newest of their repository)"
        return 0
    fi

    while IFS= read -r id; do
        [[ -z "${id}" ]] && continue
        if [[ "${DRY_RUN}" == "1" ]]; then
            log "would remove ${id}"
            removed=$((removed + 1))
            continue
        fi
        # Failure is expected and fine: docker refuses to remove an image another
        # image layers on, and that is a floor beneath this script's own logic.
        #
        # One refusal is not a real conflict and must be retried with -f: an image
        # carrying more than one tag gives
        #     conflict: unable to delete <id> (must be forced) -
        #     image is referenced in multiple repositories
        # despite the wording, this fires on multiple tags within a SINGLE repository
        # too. CI pushes :latest and :<sha> on every build, so a migrated device
        # routinely holds images under two tags -- and without the retry the script
        # logs "could not remove" and keeps exactly the stale GHCR images it exists
        # to shed.
        #
        # Forced only for that message, never blanket -- and "must be forced" alone is
        # NOT specific enough. Verified against docker 28.4.0, a stopped-container
        # reference produces:
        #     conflict: unable to delete <id> (must be forced) -
        #     image is being used by stopped container <cid>
        # which also contains "must be forced", and `-f` on it succeeds: the image goes
        # and the container is left pointing at nothing. That is the precise case this
        # retry must avoid, so the guard additionally requires the refusal NOT to be a
        # container reference.
        #
        # Excluding "being used by" rather than matching "referenced in multiple
        # repositories" positively: unfamiliar wording from a future docker then means
        # no force, which is the safe direction to be wrong in. A positive match would
        # silently stop reclaiming multi-tag images if the phrasing ever changed.
        #
        # The protected set already excludes container-referenced images, but it is a
        # start-of-run snapshot -- a container appearing after it (aquila-cert-renew
        # runs one daily) would slip through. This guard is what actually holds.
        rmi_err="$(docker rmi "${id}" 2>&1 >/dev/null)" && rc=0 || rc=$?
        if (( rc != 0 )) \
            && [[ "${rmi_err}" == *"must be forced"* ]] \
            && [[ "${rmi_err}" != *"being used by"* ]]; then
            rmi_err="$(docker rmi -f "${id}" 2>&1 >/dev/null)" && rc=0 || rc=$?
            (( rc == 0 )) && log "removed ${id} (forced: image had several tags)"
        fi
        if (( rc == 0 )); then
            removed=$((removed + 1))
        else
            # Log docker's own reason rather than assuming "still referenced": a failed
            # -f retry and "cannot be forced - dependent child images" are neither, and
            # a wrong reason misleads whoever is asking why space is not being reclaimed.
            log "could not remove ${id}: ${rmi_err}"
        fi
    done <<< "${removals}"

    log "${count} images evaluated, ${removed} removed"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
