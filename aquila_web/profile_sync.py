"""On-device Managed Profile sync — the decision core of the sync agent.

``reconcile`` takes the per-device Profile Assignment (the list of S3 keys from
the ``profiles`` Device Shadow) plus an injected ``fetch`` (bytes for a key) and
brings the local ``managed/`` directory in line with it (acorn-fleet ADR-0002).

IO is injected so the logic is testable without Greengrass IPC or the network.
This is the *add* path only: a desired key with no local file is fetched and
written. Delete / edit-detection / reported state are added in 4b.
"""
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from aq_lib.profile_hash import canonical_profile_hash


@dataclass
class ReconcileResult:
    """Outcome of a reconcile, written to the shadow's ``reported`` state.

    ``present`` is the set actually on disk after syncing (``{name, version}``);
    ``mismatches`` flags advisory-sha failures so drift is visible, not silent.
    """
    present: list = field(default_factory=list)
    mismatches: list = field(default_factory=list)
    errors: list = field(default_factory=list)

# Sidecar recording the S3 version last synced per managed file, so an in-place
# edit (same key, new version) is re-pulled without a hand-maintained hash. Not
# a *.json name, so list_profiles() never mistakes it for a Profile.
_SIDECAR = ".sync_state"


def _filename(key: str) -> str:
    """The on-disk basename for an S3 key (e.g. ``profiles/X.json`` -> ``X.json``)."""
    return key.rsplit("/", 1)[-1]


def _load_state(managed_dir: Path) -> dict:
    path = managed_dir / _SIDECAR
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return {}
    return {}


def _save_state(managed_dir: Path, state: dict) -> None:
    (managed_dir / _SIDECAR).write_text(json.dumps(state))


def _present(managed_dir: Path, state: dict) -> list:
    """The managed profiles currently on disk, with their synced versions."""
    return [
        {"name": path.name, "version": state.get(path.name)}
        for path in sorted(managed_dir.glob("*.json"))
    ]


def _normalize_entry(entry) -> Optional[dict]:
    """One desired-list entry → the ``{"key", "sha256"?}`` dict reconcile wants.

    Tolerant of hand-authored shadows (ADR-0002 v1 = raw CLI/console): an entry may
    be a bare S3-key **string** (normalized to ``{"key": ...}``) or an **object**
    with a ``key`` and optional ``sha256``. Anything without a usable key is dropped.
    """
    if isinstance(entry, str):
        return {"key": entry}
    if isinstance(entry, dict) and isinstance(entry.get("key"), str):
        out = {"key": entry["key"]}
        if entry.get("sha256") is not None:
            out["sha256"] = entry["sha256"]
        return out
    return None


def parse_desired(shadow_doc: Optional[dict]) -> Optional[list[dict]]:
    """The per-device Profile Assignment from the ``profiles`` shadow document.

    Returns the normalized ``[{"key", "sha256"?}]`` list reconcile() consumes.
    Fail-safe on ambiguity (ADR-0002 "keep last-synced set" / fail-closed):
    ``None`` means the assignment is **UNAVAILABLE** — shadow unreadable/absent, or
    no ``profiles`` declared — so reconcile keeps the cache. An **explicit empty
    list** (``profiles: []``) is a deliberate detach-all and passes through as ``[]``.
    """
    desired = (shadow_doc or {}).get("state", {}).get("desired", {})
    profiles = desired.get("profiles")
    # Absent `profiles` (or no shadow at all) is ambiguous → UNAVAILABLE, keep the
    # cache. Only an explicitly-present list (including []) is an assignment.
    if not isinstance(profiles, list):
        return None
    return [entry for entry in (_normalize_entry(p) for p in profiles) if entry]


def reported_state(result: "ReconcileResult") -> dict:
    """The ``reported`` state to write into the ``profiles`` shadow after a reconcile.

    Always reports ``profiles`` (the set on disk, so the operator can confirm the
    assignment took). ``mismatches`` / ``errors`` are included only when non-empty,
    so a clean sync leaves the shadow uncluttered but a drift/failure stays visible.
    """
    reported: dict = {"profiles": result.present}
    if result.mismatches:
        reported["mismatches"] = result.mismatches
    if result.errors:
        reported["errors"] = result.errors
    return reported


def reconcile(
    desired: list[dict],
    managed_dir: Path,
    fetch: Callable[[str], bytes],
    remote_version: Optional[Callable[[str], str]] = None,
) -> ReconcileResult:
    """Reconcile ``managed_dir`` against the desired Profile Assignment.

    Each entry in ``desired`` is a dict with at least a ``key`` (the S3 object
    key). A key is (re-)fetched when its file is missing, or — when
    ``remote_version`` is supplied — when the object's current version differs
    from the last synced one (in-place edit detection). A managed profile no
    longer in ``desired`` is deleted. ``local/`` profiles are a separate
    directory reconcile is never handed, so they are never touched.
    """
    managed_dir = Path(managed_dir)
    managed_dir.mkdir(parents=True, exist_ok=True)
    state = _load_state(managed_dir)

    # desired is None means the assignment is UNAVAILABLE (shadow unreadable /
    # offline) — distinct from an explicitly empty [] (which detaches all). Keep
    # the cached set intact and report it; never fetch or delete on unknown.
    if desired is None:
        return ReconcileResult(present=_present(managed_dir, state))

    mismatches = []
    errors = []
    desired_filenames = {_filename(entry["key"]) for entry in desired}

    # Add / update: fetch when missing, or when the remote version changed.
    for entry in desired:
        key = entry["key"]
        name = _filename(key)
        dest = managed_dir / name
        version = remote_version(key) if remote_version is not None else None
        needs_fetch = (not dest.exists()) or (
            version is not None and state.get(name) != version
        )
        if needs_fetch:
            # A failed fetch (S3 unreachable, transient error) must not crash
            # the reconcile or disturb the cache — surface it and move on; the
            # key is simply retried on the next reconcile.
            try:
                body = fetch(key)
            except Exception as exc:
                errors.append({"name": name, "error": str(exc)})
                continue
            # Advisory sha256 (optional): if declared and the fetched bytes
            # don't match, surface the mismatch and do NOT install — a wrong or
            # corrupt object should be visible, never silently applied.
            declared = entry.get("sha256")
            if declared is not None:
                actual = hashlib.sha256(body).hexdigest()
                if actual != declared.split(":")[-1]:
                    mismatches.append(
                        {"name": name, "expected": declared, "actual": actual}
                    )
                    continue
            dest.write_bytes(body)
            if version is not None:
                state[name] = version

    # Detach: a managed profile no longer in desired is removed. Only *.json
    # profiles are considered (never the sync sidecar).
    for path in managed_dir.glob("*.json"):
        if path.name not in desired_filenames:
            path.unlink()
            state.pop(path.name, None)

    _save_state(managed_dir, state)

    return ReconcileResult(
        present=_present(managed_dir, state),
        mismatches=mismatches,
        errors=errors,
    )


def capture_local_profile(
    profile_path: Path,
    local_dir: Path,
    upload: Callable[[str, bytes], None],
) -> Optional[dict]:
    """Capture a Run's Local Profile up to S3 so its recipe is reconstructable.

    Managed Profiles already live in S3 (reconstructable by their recorded sha),
    so only Local Profiles need capturing. Uploads the raw bytes under a
    content-addressed key derived from the canonical sha, matching the
    ``profile_sha256`` the Run records — so re-running the same Local Profile
    targets the same key (idempotent, no duplicate object). Returns
    ``{"key", "sha256"}`` on capture, or ``None`` when the profile is not local.
    """
    profile_path = Path(profile_path)
    try:
        profile_path.resolve().relative_to(Path(local_dir).resolve())
    except ValueError:
        return None  # not a Local Profile — already in S3, nothing to capture
    body = profile_path.read_bytes()
    sha = canonical_profile_hash(json.loads(body))
    key = f"profiles/captured/{sha.split(':')[-1]}.json"
    upload(key, body)
    return {"key": key, "sha256": sha}
