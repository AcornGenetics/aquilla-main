"""On-device Managed Profile sync — the decision core of the sync agent.

``reconcile`` takes the per-device Profile Assignment (the list of S3 keys from
the ``profiles`` Device Shadow) plus an injected ``fetch`` (bytes for a key) and
brings the local ``managed/`` directory in line with it (acorn-fleet ADR-0002).

IO is injected so the logic is testable without Greengrass IPC or the network.
This is the *add* path only: a desired key with no local file is fetched and
written. Delete / edit-detection / reported state are added in 4b.
"""
from pathlib import Path
from typing import Callable


def _filename(key: str) -> str:
    """The on-disk basename for an S3 key (e.g. ``profiles/X.json`` -> ``X.json``)."""
    return key.rsplit("/", 1)[-1]


def reconcile(
    desired: list[dict],
    managed_dir: Path,
    fetch: Callable[[str], bytes],
) -> None:
    """Reconcile ``managed_dir`` against the desired Profile Assignment.

    Each entry in ``desired`` is a dict with at least a ``key`` (the S3 object
    key). A key whose file is not already present is fetched and written.
    ``local/`` profiles are not represented here and are never touched.
    """
    managed_dir = Path(managed_dir)
    managed_dir.mkdir(parents=True, exist_ok=True)

    for entry in desired:
        key = entry["key"]
        dest = managed_dir / _filename(key)
        if not dest.exists():
            dest.write_bytes(fetch(key))
