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


def test_detaches_a_profile_removed_from_desired(tmp_path):
    """A managed profile whose key left the shadow's desired list is deleted."""
    managed = tmp_path / "managed"
    managed.mkdir()
    (managed / "Keep.json").write_bytes(b"keep")
    (managed / "Drop.json").write_bytes(b"drop")

    reconcile(
        desired=[{"key": "profiles/Keep.json"}],
        managed_dir=managed,
        fetch=lambda key: b"keep",
    )

    assert (managed / "Keep.json").exists()
    assert not (managed / "Drop.json").exists()


def test_refetches_when_remote_version_changed(tmp_path):
    """An in-place edit (same key, new S3 version) is detected and re-pulled."""
    managed = tmp_path / "managed"
    bodies = {"v1": b"old recipe", "v2": b"new recipe"}
    state = {"cur": "v1"}

    def fetch(key):
        return bodies[state["cur"]]

    def remote_version(key):
        return state["cur"]

    desired = [{"key": "profiles/P.json"}]
    reconcile(desired, managed, fetch, remote_version)
    assert (managed / "P.json").read_bytes() == b"old recipe"

    state["cur"] = "v2"
    reconcile(desired, managed, fetch, remote_version)
    assert (managed / "P.json").read_bytes() == b"new recipe"


def test_does_not_refetch_when_remote_version_unchanged(tmp_path):
    """An unchanged S3 version is not re-downloaded on the next reconcile."""
    managed = tmp_path / "managed"
    fetches = []

    def fetch(key):
        fetches.append(key)
        return b"x"

    desired = [{"key": "profiles/P.json"}]
    reconcile(desired, managed, fetch, remote_version=lambda key: "v1")
    reconcile(desired, managed, fetch, remote_version=lambda key: "v1")

    assert fetches == ["profiles/P.json"]  # fetched once, not twice


def test_reports_the_applied_set(tmp_path):
    """reconcile returns what is actually on disk after syncing — the payload
    the agent writes to the shadow's reported state."""
    managed = tmp_path / "managed"
    reconcile(
        [{"key": "profiles/A.json"}, {"key": "profiles/B.json"}],
        managed, fetch=lambda key: b"x",
    )

    result = reconcile([{"key": "profiles/A.json"}], managed, fetch=lambda key: b"x")

    assert {p["name"] for p in result.present} == {"A.json"}  # B was detached


def test_reconcile_is_idempotent(tmp_path):
    """A second reconcile with unchanged inputs fetches nothing, deletes
    nothing, and reports the same set."""
    managed = tmp_path / "managed"
    desired = [{"key": "profiles/A.json"}, {"key": "profiles/B.json"}]
    fetches = []

    def fetch(key):
        fetches.append(key)
        return b"x"

    reconcile(desired, managed, fetch, remote_version=lambda key: "v1")
    result = reconcile(desired, managed, fetch, remote_version=lambda key: "v1")

    assert len(fetches) == 2  # only the initial two, no re-fetch
    assert {p["name"] for p in result.present} == {"A.json", "B.json"}
    assert (managed / "A.json").exists() and (managed / "B.json").exists()


def test_advisory_sha_mismatch_is_flagged_not_installed(tmp_path):
    """If a desired entry declares a sha256 that the fetched bytes don't match,
    the mismatch is surfaced (not silently installed) so drift is visible."""
    managed = tmp_path / "managed"
    result = reconcile(
        [{"key": "profiles/P.json", "sha256": "0" * 64}],  # deliberately wrong
        managed,
        fetch=lambda key: b"actual bytes that hash to something else",
    )

    assert any(m["name"] == "P.json" for m in result.mismatches)
    assert not (managed / "P.json").exists()


def test_matching_advisory_sha_installs_normally(tmp_path):
    """A correct advisory sha256 installs the profile with no mismatch."""
    import hashlib
    managed = tmp_path / "managed"
    body = b'{"title": "P"}'
    good = hashlib.sha256(body).hexdigest()

    result = reconcile(
        [{"key": "profiles/P.json", "sha256": good}],
        managed,
        fetch=lambda key: body,
    )

    assert result.mismatches == []
    assert (managed / "P.json").read_bytes() == body
