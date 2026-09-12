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


@dataclass
class ReconcileResult:
    """Outcome of a reconcile, written to the shadow's ``reported`` state.

    ``present`` is the set actually on disk after syncing (``{name, version}``);
    ``mismatches`` flags advisory-sha failures so drift is visible, not silent.
    """
    present: list = field(default_factory=list)
    mismatches: list = field(default_factory=list)

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
    mismatches = []

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
            body = fetch(key)
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

    present = [
        {"name": path.name, "version": state.get(path.name)}
        for path in sorted(managed_dir.glob("*.json"))
    ]
    return ReconcileResult(present=present, mismatches=mismatches)
