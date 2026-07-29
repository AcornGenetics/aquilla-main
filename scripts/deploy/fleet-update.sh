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
# correctly detects an update -- while the bulk blob transfer stalls.
#
# Two things follow, and they pull in opposite directions:
#
#   Merely *enabling* IPv6 achieves nothing. Both Go (dockerd) and glibc already prefer
#   IPv6 over IPv4 when both work, so a device with usable IPv6 is already trying it.
#
#   Forcing IPv6 does help, but only somewhere specific. In the field a stuck device
#   completed its update after IPv4 was switched off by hand. With ghcr.io having no
#   AAAA, a v6-only pull can only authenticate where the network runs NAT64/DNS64 --
#   so that is the situation being reproduced, and the gate below tests for exactly it.
#
# Hence: retry on IPv4 first (which is what helps everywhere), and only as a last resort
# -- the update has already failed by then -- drop the IPv4 default route for one
# attempt, where the network can actually support that. This is deliberately the final
# thing tried, never a first move.

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

# ipv6_only_pull_possible -- can the WHOLE pull complete with IPv4 out of the way?
#
# ghcr.io publishes no AAAA record, so on an ordinary dual-stack network a v6-only pull
# cannot even authenticate. It works only where the network runs NAT64/DNS64: an
# IPv6-mostly setup that synthesises addresses for IPv4-only servers and translates on
# the way out. Reaching ghcr.io over IPv6 is a direct test for exactly that, and it is
# the situation observed in the field, where forcing a stuck device to IPv6 completed
# the update.
#
# Gating on this keeps us from dropping IPv4 anywhere it could not possibly help.
ipv6_only_pull_possible() {
    ip -6 route show default 2>/dev/null | grep -q . || return 1
    curl -6 -s -o /dev/null --max-time 8 "https://ghcr.io/v2/" >/dev/null 2>&1
}

# _restore_ipv4 <saved-route>
_restore_ipv4() {
    [[ -n "${1:-}" ]] && ip route replace ${1} 2>/dev/null || true
}

# _pull_ipv6_only <timeout-seconds> <command...>
#
# The last thing tried before giving up: remove the IPv4 default route so the pull has
# no choice but IPv6, attempt it once, then put the route back.
#
# Safety, because this briefly takes the device off IPv4 -- which can interrupt remote
# access for the duration:
#   - only the default ROUTE is removed, never an address or interface, so restoring is
#     a single re-add;
#   - a trap restores it on any exit, including Ctrl-C or a failure mid-pull;
#   - a detached watchdog restores it even if this shell is killed outright;
#   - nothing is written to persistent config, so a reboot also heals it.
_pull_ipv6_only() {
    local timeout_s=$1; shift
    local saved rc=0 watchdog

    saved=$(ip -4 route show default 2>/dev/null | head -1)
    if [[ -z "${saved}" ]]; then
        echo "  no IPv4 default route to remove -- skipping"
        return 1
    fi

    trap '_restore_ipv4 "${saved}"' EXIT INT TERM
    # Detached from this shell's stdout: an inherited pipe would keep the caller
    # blocked until the watchdog's sleep expired, long after the pull finished.
    ( sleep $((timeout_s + 60)); ip route replace ${saved} 2>/dev/null || true ) \
        >/dev/null 2>&1 &
    watchdog=$!

    echo "  removing the IPv4 default route for this attempt (restored afterwards)"
    ip -4 route del default 2>/dev/null || true

    _run_pull "${timeout_s}" "$@" || rc=$?

    # Kill the sleep first: killing only the subshell orphans its child, which would
    # linger for the full watchdog interval on every update.
    pkill -P "${watchdog}" 2>/dev/null || true
    kill "${watchdog}" 2>/dev/null || true
    _restore_ipv4 "${saved}"
    trap - EXIT INT TERM
    echo "  IPv4 default route restored"
    return "${rc}"
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

    # Every IPv4 attempt died on transport. One last thing before giving up: force the
    # pull onto IPv6. This is worth trying precisely because the update has already
    # failed -- the downside is a brief interruption on a device that is stuck anyway.
    echo "==> IPv4 exhausted; considering an IPv6-only attempt"

    if ! ipv6_only_pull_possible; then
        # Either no IPv6 at all, or IPv6 without NAT64 -- in which case ghcr.io (no
        # AAAA) is unreachable v6-only and dropping IPv4 would fail at authentication
        # while costing the device its connectivity. Not worth it.
        echo "==> IPv6-only pull not possible here (no v6 route, or ghcr.io unreachable over IPv6)." >&2
        echo "==> pull FAILED (families tried: ${_PULL_FAMILIES_TRIED})" >&2
        _write_pull_outcome failed "${_PULL_FAMILIES_TRIED}" "IPv4 transfer failed; no viable IPv6 path at this site"
        return 1
    fi

    _PULL_FAMILIES_TRIED="ipv4,ipv6"
    for ((attempt = 1; attempt <= PULL_IPV6_ATTEMPTS; attempt++)); do
        remaining=$((PULL_TOTAL_BUDGET_SECONDS - ($(date +%s) - started)))
        (( remaining <= 0 )) && break

        echo "==> IPv6-only pull attempt ${attempt}/${PULL_IPV6_ATTEMPTS} (${remaining}s of budget left)"
        rc=0; _pull_ipv6_only "${remaining}" "$@" || rc=$?
        if (( rc == 0 )); then
            # Loud on purpose: a device needing this on every update has a site network
            # problem to fix upstream, not to paper over here.
            echo "==> pull succeeded over IPv6 after IPv4 failed -- site IPv4 path is degraded"
            _write_pull_outcome ok "${_PULL_FAMILIES_TRIED}" "IPv4 failed; completed over IPv6"
            return 0
        fi
        kind=$(classify_pull_error "${_PULL_LAST_ERROR}")
        echo "==> IPv6-only attempt ${attempt} failed (${kind})"
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
