"""Matched-pair Container Health + operator-gate logic for the Greengrass agent.

Pure functions only (no Greengrass IPC, no FastAPI) so the run-gate, the shadow
reporter, and the operator banner all share one source of truth. A Sentri's api
and ui containers must run the SAME build; a mismatch is the sn04 failure mode
and blocks runs (ADR-022 invariant A).
"""


def is_matched_pair(api_sha, ui_sha):
    """True only when the api and ui containers run the same, known build.

    Unknown identity (missing/empty SHA) fails safe as *not* matched, so a
    container that has not reported blocks runs rather than passing silently.
    """
    return bool(api_sha) and api_sha == ui_sha


def runs_allowed(api_sha, ui_sha):
    """Whether an assay run may start, given the running container SHAs.

    Blocks only a *known* mismatch (both SHAs present and different) — the sn04
    case. Unknown identity (a SHA missing) cannot be enforced and must not brick
    the instrument, so it is allowed. Distinct from is_matched_pair, which treats
    unknown as "not matched" for honest Container-Health reporting.
    """
    if not api_sha or not ui_sha:
        return True
    return api_sha == ui_sha


def build_shadow_report(api_sha, ui_sha):
    """The Device-Shadow reported state: the running build SHAs + Container Health."""
    return {
        "images": {"api": api_sha, "ui": ui_sha},
        "container_health": "matched" if is_matched_pair(api_sha, ui_sha) else "mismatched",
    }


def update_banner(last_update_failed):
    """Operator notice when an update failed and the device kept the old version.

    Non-blocking: a failed update rolls back to a working build, so the operator
    keeps running — this only informs them a newer version did not take.
    """
    if not last_update_failed:
        return None
    return {
        "level": "warning",
        "blocking": False,
        "message": "Last update failed — running the previous version.",
    }


def should_defer_update(assay_running, operator_approved):
    """Whether to DeferComponentUpdate instead of switching now.

    The image is pre-staged; the switch is held (deferred) until the device is
    idle AND the operator has approved. So "Update" is instant when tapped, and a
    running assay is never interrupted.
    """
    return assay_running or not operator_approved
