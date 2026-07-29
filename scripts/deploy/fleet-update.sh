#!/usr/bin/env bash
set -euo pipefail

# Device-side fleet update. Installed standalone as /opt/fleet/update.sh by
# deployment2.sh (a single curl), so this file must stay self-contained -- it has no
# sibling libraries to source on a provisioned device.
#
# Sourcing this file defines the functions without running the update (see the main
# guard at the bottom), which is how the tests exercise the retry logic offline.

FLEET_ENV="${FLEET_ENV:-/opt/fleet/.env}"
DEVICE_ENV="${DEVICE_ENV:-/opt/aquila/config/device.env}"
COMPOSE_FILE="${COMPOSE_FILE:-/opt/fleet/docker-compose.yml}"

# --- image pull: retry, and fall back to IPv6 when IPv4 can't carry it (#357) -------
#
# A pull is two conversations with two different hosts:
#   auth + manifest -> ghcr.io                              (a few KB, NO AAAA record)
#   blob / layers   -> pkg-containers.githubusercontent.com (hundreds of MB, HAS AAAA)
# On a degraded IPv4 path the small manifest fetch still succeeds -- so the device
# correctly detects an update -- while the bulk blob transfer stalls. Because the blob
# host is v6-capable, bringing IPv6 up rescues exactly the leg that fails. This was
# observed in the field: switching a stuck device to IPv6 completed the update.
#
# We do NOT force a family per connection (docker exposes no such flag, and pinning CDN
# addresses into /etc/hosts rots as the CDN rotates). We make IPv6 usable and let
# glibc's RFC 6724 address selection prefer it for AAAA-bearing hosts. ghcr.io publishes
# no AAAA, so auth/manifest stay on IPv4 by themselves -- no special-casing needed.

PULL_BLOB_HOST="${PULL_BLOB_HOST:-pkg-containers.githubusercontent.com}"

# Breadcrumb read back by the backend for /update/status (#357). The backend cannot
# observe this itself: the operator's Update button drives Watchtower, which performs
# its own pull and never runs this script. So a device-side pull records what it tried
# here, and the API surfaces it -- explicitly as "the last device-side pull", not as a
# claim about the Watchtower path.
PULL_OUTCOME_PATH="${PULL_OUTCOME_PATH:-/opt/fleet/last_pull.json}"

# An operator is standing at the device. Long enough to ride out a slow link, short
# enough not to look hung. Total wall clock across every attempt.
PULL_TOTAL_BUDGET_SECONDS="${PULL_TOTAL_BUDGET_SECONDS:-480}"
PULL_IPV4_ATTEMPTS="${PULL_IPV4_ATTEMPTS:-3}"
PULL_IPV6_ATTEMPTS="${PULL_IPV6_ATTEMPTS:-2}"
PULL_BACKOFF_SECONDS="${PULL_BACKOFF_SECONDS:-5}"

# classify_pull_error <text> -> auth | notfound | transport | unknown
#
# Decide whether a failed pull is worth retrying. Auth and missing-tag failures are
# deterministic: retrying burns the operator's budget to reach the same error, and no
# change of address family can turn a 401 into a 200. Only transport failures retry.
#
# Order matters -- a message can carry both a status code and a transport-ish word
# ("unexpected status code 401"), so deterministic patterns are matched first.
classify_pull_error() {
    local text="$1"
    local lower
    lower=$(printf '%s' "${text}" | tr '[:upper:]' '[:lower:]')

    # Status codes are matched with their surrounding words, never bare. Pull errors
    # quote image digests, and "401"/"403"/"404" all occur inside plain hex -- a bare
    # *"401"* pattern would read a digest inside a timeout message as an auth failure
    # and abort a retry that would have succeeded.
    case "${lower}" in
        *unauthorized*|*"authentication required"*|*"access denied"*|*denied:*|\
        *forbidden*|*"invalid username or password"*|\
        *"status code: 401"*|*"status code: 403"*|*"status 401"*|*"status 403"*)
            echo "auth"; return 0 ;;
    esac

    case "${lower}" in
        *"manifest unknown"*|*"not found"*|*"repository does not exist"*|\
        *"no such manifest"*|*"reference does not exist"*|\
        *"status code: 404"*|*"status 404"*)
            echo "notfound"; return 0 ;;
    esac

    case "${lower}" in
        *"i/o timeout"*|*"tls handshake timeout"*|*"unexpected eof"*|*"connection reset"*|\
        *"connection refused"*|*"context deadline exceeded"*|*"no route to host"*|\
        *"temporary failure in name resolution"*|*"network is unreachable"*|*"broken pipe"*|\
        *"timeout awaiting"*|*"failed to copy"*|*"error pulling image configuration"*|\
        *"read: connection"*|*"unexpected status code 5"*|*"server misbehaving"*|*eof*)
            echo "transport"; return 0 ;;
    esac

    # Unknown wording is left retryable by the caller rather than fatal: a future
    # docker/containerd release phrasing a timeout differently must not strand a device
    # on an old image. The budget still bounds how long that costs.
    echo "unknown"
}

# ipv6_usable -- true only with real internet IPv6 that reaches the blob host.
#
# Two traps this guards against:
#   - Tailscale hands out an fd7a::/8 ULA address, so "has a global v6 address" is not
#     enough; devices look v6-capable while having no route off-link. Requiring a
#     default route excludes that.
#   - A router can advertise v6 with no working upstream (blackholed), which would make
#     the fallback slower than no fallback. So we prove the path end to end.
ipv6_usable() {
    ip -6 route show default 2>/dev/null | grep -q . || return 1
    # No -f: any HTTP status proves the path carried a request. Only a failure to
    # connect at all (non-zero curl exit) means IPv6 is unusable here.
    curl -6 -s -o /dev/null --max-time 8 "https://${PULL_BLOB_HOST}/" >/dev/null 2>&1
}

# enable_ipv6 -- undo an explicitly disabled stack.
#
# Some device images ship with IPv6 switched off in sysctl; that is the case we can fix
# locally. If the site's network simply doesn't route v6, there is nothing to enable --
# ipv6_usable() stays false and we report that rather than pretend a fallback exists.
enable_ipv6() {
    local persisted="/etc/sysctl.d/99-aquila-ipv6.conf"

    if [[ "$(sysctl -n net.ipv6.conf.all.disable_ipv6 2>/dev/null || echo 0)" == "1" ]]; then
        echo "  IPv6 was disabled in sysctl -- enabling it"
        sysctl -w net.ipv6.conf.all.disable_ipv6=0 >/dev/null 2>&1 || return 1
        sysctl -w net.ipv6.conf.default.disable_ipv6=0 >/dev/null 2>&1 || true
        # Persist, or the next reboot silently reverts the device to a broken update path.
        printf 'net.ipv6.conf.all.disable_ipv6 = 0\nnet.ipv6.conf.default.disable_ipv6 = 0\n' \
            > "${persisted}" 2>/dev/null || true
        sleep 5   # SLAAC needs a moment to land a route once the stack is back up
    fi
}

# _pull_timeout <seconds> <command...>
# Devices (Debian) ship coreutils `timeout`; dev machines (macOS) may not. Rather than
# failing every pull with "command not found", run without the cap and let the attempt
# counter bound the work -- a hung pull then can't be preempted mid-attempt, which is
# acceptable on a workstation and never happens on a device.
_pull_timeout() {
    local secs=$1; shift
    if command -v timeout >/dev/null 2>&1; then
        timeout "${secs}" "$@"
    elif command -v gtimeout >/dev/null 2>&1; then
        gtimeout "${secs}" "$@"
    else
        "$@"
    fi
}

# _run_pull <timeout-seconds> <command...>
# One attempt. Echoes output to the operator while capturing it for classification;
# leaves the captured text in _PULL_LAST_ERROR and returns the command's status.
_run_pull() {
    local timeout_s=$1; shift
    local tmp rc errexit_was_set=0
    tmp=$(mktemp)

    # This script runs under `set -euo pipefail`. A failing pull is an expected outcome
    # here, not a reason to abort. PIPESTATUS must be read from the pipeline itself:
    # without pipefail a pipeline reports tee's status (always 0), which would report
    # every failed pull as a success.
    [[ $- == *e* ]] && errexit_was_set=1
    set +e
    _pull_timeout "${timeout_s}" "$@" 2>&1 | tee "${tmp}"
    rc=${PIPESTATUS[0]}
    (( errexit_was_set )) && set -e

    _PULL_LAST_ERROR=$(cat "${tmp}")
    rm -f "${tmp}"
    return "${rc}"
}

# _write_pull_outcome <result> <families> <detail>
# Best-effort: a device that cannot write the breadcrumb must still complete its
# update, so every failure here is swallowed.
_write_pull_outcome() {
    local result=$1 families=$2 detail=$3
    printf '{"result":"%s","families_tried":"%s","detail":"%s","at":"%s"}\n' \
        "${result}" "${families}" "${detail}" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        > "${PULL_OUTCOME_PATH}" 2>/dev/null || true
}

# pull_with_fallback <pull-command...>
#
# Retry over the default path, then -- only for transport failures -- bring IPv6 up and
# retry there. Names every family attempted on the way out, so support can tell "no IPv6
# at this site" from "registry down" from "bad token" without guessing.
pull_with_fallback() {
    local started attempt rc kind remaining
    started=$(date +%s)
    _PULL_FAMILIES_TRIED="ipv4"

    for ((attempt = 1; attempt <= PULL_IPV4_ATTEMPTS; attempt++)); do
        remaining=$((PULL_TOTAL_BUDGET_SECONDS - ($(date +%s) - started)))
        (( remaining <= 0 )) && break

        echo "==> pull attempt ${attempt}/${PULL_IPV4_ATTEMPTS} (${remaining}s of budget left)"
        rc=0; _run_pull "${remaining}" "$@" || rc=$?
        if (( rc == 0 )); then
            echo "==> pull succeeded (families tried: ${_PULL_FAMILIES_TRIED})"
            _write_pull_outcome ok "${_PULL_FAMILIES_TRIED}" ""
            return 0
        fi

        kind=$(classify_pull_error "${_PULL_LAST_ERROR}")
        case "${kind}" in
            auth)
                echo "==> pull failed: credentials rejected. Not retrying -- check GHCR_TOKEN." >&2
                _write_pull_outcome failed "${_PULL_FAMILIES_TRIED}" "credentials rejected"
                return 1 ;;
            notfound)
                echo "==> pull failed: image/tag not found. Not retrying -- check IMAGE_TAG." >&2
                _write_pull_outcome failed "${_PULL_FAMILIES_TRIED}" "image or tag not found"
                return 1 ;;
        esac
        echo "==> attempt ${attempt} failed (${kind}); backing off ${PULL_BACKOFF_SECONDS}s"
        sleep "${PULL_BACKOFF_SECONDS}"
    done

    # Every IPv4 attempt died on transport -- the case IPv6 exists to rescue.
    echo "==> IPv4 exhausted; trying IPv6 for the blob transfer"
    enable_ipv6 || true

    if ! ipv6_usable; then
        echo "==> no usable IPv6 here (no v6 default route, or ${PULL_BLOB_HOST} unreachable over v6)." >&2
        echo "==> pull FAILED (families tried: ${_PULL_FAMILIES_TRIED})" >&2
        _write_pull_outcome failed "${_PULL_FAMILIES_TRIED}" "IPv4 transfer failed and no usable IPv6 at this site"
        return 1
    fi

    _PULL_FAMILIES_TRIED="ipv4,ipv6"
    for ((attempt = 1; attempt <= PULL_IPV6_ATTEMPTS; attempt++)); do
        remaining=$((PULL_TOTAL_BUDGET_SECONDS - ($(date +%s) - started)))
        (( remaining <= 0 )) && break

        echo "==> IPv6 pull attempt ${attempt}/${PULL_IPV6_ATTEMPTS} (${remaining}s of budget left)"
        rc=0; _run_pull "${remaining}" "$@" || rc=$?
        if (( rc == 0 )); then
            # Loud on purpose: a device needing the v6 fallback on every update has a
            # site network problem to fix upstream, not to paper over here.
            echo "==> pull succeeded over IPv6 after IPv4 failed -- site IPv4 path is degraded"
            _write_pull_outcome ok "${_PULL_FAMILIES_TRIED}" "IPv4 failed; completed over IPv6"
            return 0
        fi
        kind=$(classify_pull_error "${_PULL_LAST_ERROR}")
        echo "==> IPv6 attempt ${attempt} failed (${kind})"
        sleep "${PULL_BACKOFF_SECONDS}"
    done

    echo "==> pull FAILED over every path (families tried: ${_PULL_FAMILIES_TRIED})" >&2
    _write_pull_outcome failed "${_PULL_FAMILIES_TRIED}" "transfer failed over both IPv4 and IPv6"
    return 1
}

_upsert_env() {
    local key=$1 val=$2 file=$3
    if grep -q "^${key}=" "${file}"; then
        sed -i "s|^${key}=.*|${key}=${val}|" "${file}"
    else
        echo "${key}=${val}" >> "${file}"
    fi
}

main() {
    local GHCR_TOKEN GHCR_TOKEN_2 GHCR_REPO IMAGE_TAG _DIGEST _DIGEST_UI

    GHCR_TOKEN=$(grep ^GHCR_TOKEN= "${DEVICE_ENV}" | cut -d= -f2)
    GHCR_TOKEN_2=$(grep ^GHCR_TOKEN_2= "${DEVICE_ENV}" 2>/dev/null | cut -d= -f2 || echo "")
    GHCR_REPO=$(grep ^GHCR_REPO "${FLEET_ENV}" | cut -d= -f2)
    IMAGE_TAG=$(grep ^IMAGE_TAG "${FLEET_ENV}" | cut -d= -f2)

    # If a second token is configured, validate the primary and fall back to it.
    # This allows zero-downtime token rotation: add GHCR_TOKEN_2 to device.env,
    # verify it works, then promote it to GHCR_TOKEN and remove GHCR_TOKEN_2.
    if [[ -n "${GHCR_TOKEN_2}" ]]; then
        if ! curl -fsSL -o /dev/null \
                -H "Authorization: token ${GHCR_TOKEN}" \
                "https://api.github.com/repos/${GHCR_REPO}" 2>/dev/null; then
            GHCR_TOKEN="${GHCR_TOKEN_2}"
        fi
    fi

    curl -fsSL \
        -H "Authorization: token ${GHCR_TOKEN}" \
        "https://raw.githubusercontent.com/${GHCR_REPO}/main/fleet-config/docker-compose.yml" \
        -o "${COMPOSE_FILE}"

    # Previously a bare `docker compose pull`: under `set -e` a single dropped
    # connection aborted the update before the digest write-back below, leaving the
    # device on the old image with nothing retried (#357).
    pull_with_fallback docker compose --env-file "${FLEET_ENV}" -f "${COMPOSE_FILE}" pull

    _DIGEST=$(docker inspect --format='{{index .RepoDigests 0}}' \
        "ghcr.io/${GHCR_REPO}-api:${IMAGE_TAG}" 2>/dev/null | awk -F@ '{print $2}')
    _DIGEST_UI=$(docker inspect --format='{{index .RepoDigests 0}}' \
        "ghcr.io/${GHCR_REPO}-ui:${IMAGE_TAG}" 2>/dev/null | awk -F@ '{print $2}')

    _upsert_env RUNNING_IMAGE_DIGEST    "${_DIGEST:-}"    "${FLEET_ENV}"
    _upsert_env RUNNING_IMAGE_DIGEST_UI "${_DIGEST_UI:-}" "${FLEET_ENV}"

    # --force-recreate: a same-tag digest change (e.g. pilot->new pilot) otherwise
    #   leaves the old container running; force it so the pulled image is swapped in.
    # --remove-orphans: clear any half-finished Watchtower swap leftovers
    #   (<hash>_aquila-backend) so they don't linger and fight for the same ports.
    docker compose --env-file "${FLEET_ENV}" -f "${COMPOSE_FILE}" up -d --force-recreate --remove-orphans

    mkdir -p /opt/aquila/tests
}

# Only run when executed. Sourcing defines the functions for the tests without
# touching the device.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
