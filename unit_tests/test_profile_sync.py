"""
Unit tests for aquila_web/profile_sync.py — reconcile(desired, managed_dir, fetch).

The on-device sync agent's decision core (acorn-fleet ADR-0002, issue #457):
given the per-device Profile Assignment (a list of S3 keys from the `profiles`
shadow) and a way to fetch an object's bytes, it reconciles the local
``managed/`` directory. 3b covers the *add* path only; delete / edit-detection /
reported state are 4b. IO is injected, so no network or Greengrass IPC is needed.
Marked ``unit``.
"""
import pytest

from aquila_web.profile_sync import reconcile

pytestmark = pytest.mark.unit


def test_writes_a_newly_assigned_profile_into_managed(tmp_path):
    """A desired key with no local file is fetched from S3 and written."""
    managed = tmp_path / "managed"
    body = b'{"title": "Beer Spoilers", "steps": []}'

    reconcile(
        desired=[{"key": "profiles/Beer_Spoilers.json"}],
        managed_dir=managed,
        fetch=lambda key: body,
    )

    assert (managed / "Beer_Spoilers.json").read_bytes() == body


def test_does_not_refetch_a_profile_already_present(tmp_path):
    """An already-present managed profile is left as-is (no redundant fetch)."""
    managed = tmp_path / "managed"
    managed.mkdir()
    (managed / "Beer_Spoilers.json").write_bytes(b"original")

    def _fetch(key):
        raise AssertionError(f"should not fetch already-present {key}")

    reconcile(
        desired=[{"key": "profiles/Beer_Spoilers.json"}],
        managed_dir=managed,
        fetch=_fetch,
    )

    assert (managed / "Beer_Spoilers.json").read_bytes() == b"original"
