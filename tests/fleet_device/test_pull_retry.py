"""Retry + IPv6 fallback for the device image pull (#357).

These tests source scripts/deploy/fleet-update.sh and call its shell functions
directly, so they exercise real behaviour rather than asserting on source text.
Sourcing is safe: the script only runs the update when executed, not when sourced.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path("scripts/deploy/fleet-update.sh")

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None, reason="bash required to exercise the shell functions"
)


def _call(function: str, *args: str, setup: str = "") -> str:
    """Source the script (defining functions only) and invoke one function."""
    quoted = " ".join(f"'{a}'" for a in args)
    script = f"source {SCRIPT}\n{setup}\n{function} {quoted}"
    result = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, timeout=60
    )
    return result.stdout.strip()


# --- error classification ---------------------------------------------------
# Real strings as docker/containerd emit them. The classifier decides whether the
# operator waits through a retry or gets told to fix a token, so both directions
# of a misclassification are expensive.

@pytest.mark.parametrize(
    "message",
    [
        "Get https://ghcr.io/v2/: net/http: TLS handshake timeout",
        "failed to copy: httpReadSeeker: failed open: unexpected EOF",
        "read tcp 10.0.0.5:443: read: connection reset by peer",
        "dial tcp: i/o timeout",
        "context deadline exceeded",
        "error pulling image configuration: download failed after attempts=1: EOF",
        "Temporary failure in name resolution",
        "connect: network is unreachable",
    ],
)
def test_transport_failures_are_retryable(message: str) -> None:
    assert _call("classify_pull_error", message) == "transport"


@pytest.mark.parametrize(
    "message",
    [
        "unauthorized: authentication required",
        "denied: denied",
        "pull access denied for ghcr.io/acorngenetics/aquilla-main-api",
        "unexpected status code: 401 Unauthorized",
        "Error response from daemon: 403 Forbidden",
    ],
)
def test_auth_failures_are_not_retried(message: str) -> None:
    """A 401 cannot be fixed by retrying or by changing address family."""
    assert _call("classify_pull_error", message) == "auth"


@pytest.mark.parametrize(
    "message",
    [
        "manifest unknown",
        "manifest for ghcr.io/acorngenetics/aquilla-main-api:nope not found",
        "unexpected status code: 404",
    ],
)
def test_missing_tag_is_not_retried(message: str) -> None:
    assert _call("classify_pull_error", message) == "notfound"


def test_digest_containing_401_is_not_mistaken_for_an_auth_failure() -> None:
    """Regression: pull errors quote hex digests, and '401'/'403'/'404' occur in hex.

    A bare substring match on the status code reads the digest below as an auth
    failure and refuses to retry a transfer that would have succeeded on attempt two.
    """
    message = (
        "failed to register layer: "
        "sha256:401403404ab9c8d7e6f5a4b3c2d1e0f9a8b7c6d5e4f3a2b1c0d9e8f7a6b5c4d3: "
        "unexpected EOF"
    )
    assert _call("classify_pull_error", message) == "transport"


def test_unknown_wording_stays_retryable() -> None:
    """A future docker release rewording a timeout must not strand a device."""
    assert _call("classify_pull_error", "something nobody has seen before") == "unknown"


# --- fallback orchestration -------------------------------------------------
# pull_with_fallback is driven with a stub "pull" command so the whole decision
# path runs offline, with no registry and no real IPv6.

FAST = "PULL_BACKOFF_SECONDS=0; PULL_TOTAL_BUDGET_SECONDS=60;"


def test_successful_pull_runs_once_and_does_not_touch_ipv6() -> None:
    setup = f"{FAST} ipv6_only_pull_possible() {{ echo IPV6_PROBED; return 1; }}"
    out = _call("pull_with_fallback", "true", setup=setup)

    assert "pull succeeded" in out
    assert "IPV6_PROBED" not in out, "a working pull must not probe IPv6"
    assert out.count("==> pull attempt") == 1


def test_auth_failure_fails_fast_without_exhausting_the_budget() -> None:
    """The operator should be told to fix the token, not made to wait out retries."""
    setup = f"{FAST} _fail() {{ echo 'unauthorized: authentication required'; return 1; }}"
    out = _call("pull_with_fallback", "_fail", setup=setup)

    assert out.count("==> pull attempt") == 1, "auth failure must not retry"
    assert "IPv4 exhausted" not in out, "auth failure must not reach the IPv6 fallback"


def test_transport_failure_retries_then_falls_back_to_ipv6() -> None:
    setup = (
        f"{FAST} PULL_IPV4_ATTEMPTS=3;"
        " _fail() { echo 'unexpected EOF'; return 1; };"
        ""
        " ipv6_only_pull_possible() { return 0; };"
        " _pull_ipv6_only() { shift; \"$@\"; }"
    )
    out = _call("pull_with_fallback", "_fail", setup=setup)

    # "==> pull attempt" is the IPv4 banner; the v6 one reads "==> IPv6 pull attempt".
    assert out.count("==> pull attempt") == 3, "should use its full IPv4 budget first"
    assert "IPv4 exhausted; considering an IPv6-only attempt" in out
    assert "IPv6-only pull attempt" in out


def test_reports_degraded_ipv4_when_ipv6_rescues_the_pull() -> None:
    """The field case: IPv4 can't carry the transfer, IPv6 can."""
    setup = (
        f"{FAST} PULL_IPV4_ATTEMPTS=1;"
        " _flaky() { [[ -f $STATE ]] && return 0; touch $STATE;"
        "            echo 'unexpected EOF'; return 1; };"
        ""
        " ipv6_only_pull_possible() { return 0; };"
        " _pull_ipv6_only() { shift; \"$@\"; };"
        " STATE=$(mktemp -u)"
    )
    out = _call("pull_with_fallback", "_flaky", setup=setup)

    assert "pull succeeded over IPv6" in out
    assert "site IPv4 path is degraded" in out, "must surface that the site needs fixing"


def test_no_ipv6_at_site_fails_with_a_diagnosable_message() -> None:
    """Both probed devices had no v6 default route -- this path must stay honest."""
    setup = (
        f"{FAST} PULL_IPV4_ATTEMPTS=1;"
        " _fail() { echo 'unexpected EOF'; return 1; };"
        ""
        " ipv6_only_pull_possible() { return 1; }"
    )
    result = subprocess.run(
        ["bash", "-c", f"source {SCRIPT}\n{setup}\npull_with_fallback _fail"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    combined = result.stdout + result.stderr

    assert result.returncode != 0, "must not report success when nothing was pulled"
    assert "IPv6-only pull not possible" in combined
    assert "families tried: ipv4" in combined


def test_failed_pull_never_reports_success() -> None:
    """Without pipefail a `cmd | tee` pipeline returns tee's status (0).

    Reading that instead of PIPESTATUS[0] would mark every failed pull as a success
    and let the update continue onto the digest write-back with a stale image.
    """
    setup = f"{FAST} PULL_IPV4_ATTEMPTS=1; ipv6_only_pull_possible() {{ return 1; }}"
    result = subprocess.run(
        ["bash", "-c", f"set +o pipefail\nsource {SCRIPT}\n{setup}\npull_with_fallback false"],
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode != 0
    assert "pull succeeded" not in result.stdout


# --- deployment shape -------------------------------------------------------

def test_script_is_self_contained_for_standalone_install() -> None:
    """deployment2.sh curls this file alone to /opt/fleet/update.sh.

    Sourcing a sibling library would break every provisioned device, since no such
    file is fetched alongside it.
    """
    code = [
        line.strip()
        for line in SCRIPT.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    sourcing = [ln for ln in code if ln.startswith("source ") or ln.startswith(". ")]
    assert not sourcing, f"must not source sibling files: {sourcing}"
    assert any('BASH_SOURCE[0]}" == "${0}"' in ln for ln in code), (
        "needs the main guard to stay sourceable"
    )


def test_pull_retains_digest_writeback_after_a_successful_pull() -> None:
    """The retry must not reorder the update: digests are captured after the pull."""
    text = SCRIPT.read_text()

    assert text.index("pull_with_fallback docker compose") < text.index("RepoDigests")
    assert text.index("RepoDigests") < text.index("_upsert_env RUNNING_IMAGE_DIGEST")


# --- outcome breadcrumb -----------------------------------------------------

def test_records_which_families_were_tried_for_the_backend(tmp_path) -> None:
    """/update/status reads this file; it must name the families on the v6 rescue."""
    outcome = tmp_path / "last_pull.json"
    setup = (
        f"{FAST} PULL_IPV4_ATTEMPTS=1; PULL_OUTCOME_PATH='{outcome}';"
        " _flaky() { [[ -f $STATE ]] && return 0; touch $STATE;"
        "            echo 'unexpected EOF'; return 1; };"
        ""
        " ipv6_only_pull_possible() { return 0; };"
        " _pull_ipv6_only() { shift; \"$@\"; };"
        " STATE=$(mktemp -u)"
    )
    _call("pull_with_fallback", "_flaky", setup=setup)

    recorded = json.loads(outcome.read_text())
    assert recorded["result"] == "ok"
    assert recorded["families_tried"] == "ipv4,ipv6"


def test_records_a_failure_the_backend_can_explain(tmp_path) -> None:
    outcome = tmp_path / "last_pull.json"
    setup = (
        f"{FAST} PULL_IPV4_ATTEMPTS=1; PULL_OUTCOME_PATH='{outcome}';"
        " _fail() { echo 'unexpected EOF'; return 1; };"
        ""
        " ipv6_only_pull_possible() { return 1; }"
    )
    _call("pull_with_fallback", "_fail", setup=setup)

    recorded = json.loads(outcome.read_text())
    assert recorded["result"] == "failed"
    assert "no viable IPv6 path" in recorded["detail"]


def test_unwritable_breadcrumb_does_not_fail_the_update() -> None:
    """A device that cannot write the breadcrumb must still complete its update."""
    setup = f"{FAST} PULL_OUTCOME_PATH='/nonexistent-dir/last_pull.json'"
    out = _call("pull_with_fallback", "true", setup=setup)

    assert "pull succeeded" in out


# --- the IPv6-only last resort ----------------------------------------------
# _pull_ipv6_only removes the device's IPv4 default route for one attempt. If it
# ever failed to put it back, a remote device would lose connectivity and nobody
# could reach it to fix that. These drive it with a stubbed `ip`.

IP_STUB = (
    " ip() {{ echo \"ip $*\" >> {log};"
    '   if [[ "$*" == "-4 route show default" ]]; then'
    '     echo "default via 192.168.1.1 dev wlan0 proto dhcp metric 600"; fi; }};'
)


def _ip_calls(log) -> list[str]:
    return log.read_text().splitlines() if log.exists() else []


def test_ipv4_route_is_restored_after_a_successful_ipv6_attempt(tmp_path) -> None:
    log = tmp_path / "ip.log"
    setup = IP_STUB.format(log=log)
    out = _call("_pull_ipv6_only", "60", "true", setup=setup)

    calls = _ip_calls(log)
    assert any("route del default" in c for c in calls), "should remove the v4 route"
    assert any("route replace" in c for c in calls), "must put the v4 route back"
    assert "restored" in out


def test_ipv4_route_is_restored_even_when_the_pull_fails(tmp_path) -> None:
    """The failure path is the one that matters -- it's where a device gets stranded."""
    log = tmp_path / "ip.log"
    setup = IP_STUB.format(log=log)
    result = subprocess.run(
        ["bash", "-c", f"source {SCRIPT}\n{setup}\n_pull_ipv6_only 60 false"],
        capture_output=True, text=True, timeout=60,
    )

    assert result.returncode != 0, "a failed pull must still report failure"
    assert any("route replace" in c for c in _ip_calls(log)), "route must be restored"


def test_no_ipv4_route_to_remove_is_a_no_op(tmp_path) -> None:
    """Nothing to remove means nothing to restore -- must not delete a route blindly."""
    log = tmp_path / "ip.log"
    setup = f' ip() {{ echo "ip $*" >> {log}; }};'
    result = subprocess.run(
        ["bash", "-c", f"source {SCRIPT}\n{setup}\n_pull_ipv6_only 60 true"],
        capture_output=True, text=True, timeout=60,
    )

    assert result.returncode != 0
    assert not any("route del" in c for c in _ip_calls(log))


def test_fallback_is_skipped_when_the_network_cannot_support_it(tmp_path) -> None:
    """Without NAT64, ghcr.io is unreachable v6-only: dropping IPv4 would only cost
    the device its connectivity and still fail at authentication."""
    log = tmp_path / "ip.log"
    setup = (
        f"{FAST} PULL_IPV4_ATTEMPTS=1;"
        " _fail() { echo 'unexpected EOF'; return 1; };"
        " ipv6_only_pull_possible() { return 1; };"
        f' ip() {{ echo "ip $*" >> {log}; }};'
    )
    result = subprocess.run(
        ["bash", "-c", f"source {SCRIPT}\n{setup}\npull_with_fallback _fail"],
        capture_output=True, text=True, timeout=60,
    )

    assert not any("route del" in c for c in _ip_calls(log)), "must not touch routing"
    assert "IPv6-only pull not possible" in result.stdout + result.stderr
