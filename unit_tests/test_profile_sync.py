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

from aquila_web.profile_sync import (
    ReconcileResult,
    parse_desired,
    reconcile,
    reported_state,
)

pytestmark = pytest.mark.unit


def test_reported_state_reports_what_is_on_disk():
    """reported.profiles is the set actually present after a sync (name + synced
    version) — what the operator reads back to confirm the assignment took."""
    result = ReconcileResult(present=[{"name": "x.json", "version": "v1"}])

    assert reported_state(result) == {"profiles": [{"name": "x.json", "version": "v1"}]}


def test_reported_state_surfaces_mismatches_and_errors_when_present():
    result = ReconcileResult(
        present=[{"name": "x.json", "version": "v1"}],
        mismatches=[{"name": "bad.json", "expected": "sha256:a", "actual": "sha256:b"}],
        errors=[{"name": "gone.json", "error": "NoSuchKey"}],
    )

    reported = reported_state(result)

    assert reported["profiles"] == [{"name": "x.json", "version": "v1"}]
    assert reported["mismatches"] == [
        {"name": "bad.json", "expected": "sha256:a", "actual": "sha256:b"}
    ]
    assert reported["errors"] == [{"name": "gone.json", "error": "NoSuchKey"}]


def test_reported_state_omits_empty_mismatches_and_errors():
    """A clean sync reports only `profiles` — no empty mismatch/error keys cluttering
    the shadow."""
    assert reported_state(ReconcileResult(present=[])) == {"profiles": []}


def test_parse_desired_objects_pass_through_key_and_sha():
    """The canonical Profile Assignment: desired.profiles is a list of objects,
    each with a `key` (S3 key) and an optional `sha256`. parse_desired returns
    exactly the list reconcile() consumes."""
    doc = {
        "state": {
            "desired": {
                "profiles": [
                    {"key": "profiles/x.json", "sha256": "sha256:abc"},
                    {"key": "profiles/y.json"},
                ]
            }
        }
    }

    assert parse_desired(doc) == [
        {"key": "profiles/x.json", "sha256": "sha256:abc"},
        {"key": "profiles/y.json"},
    ]


def test_parse_desired_unavailable_shadow_is_none():
    """No shadow document (unreadable/absent) → None (UNAVAILABLE), so reconcile
    keeps the cached set — never mistaken for a detach-all."""
    assert parse_desired(None) is None


def test_parse_desired_absent_profiles_key_is_none_not_detach():
    """A readable shadow that simply hasn't declared `profiles` is ambiguous, so it
    is UNAVAILABLE (None) — fail-safe. It must NOT read as an empty assignment,
    which would wipe every managed profile."""
    assert parse_desired({"state": {"desired": {"welcome": "aws-iot"}}}) is None


def test_parse_desired_explicit_empty_list_is_detach_all():
    """`profiles: []` is a deliberate detach-all and passes through as []."""
    assert parse_desired({"state": {"desired": {"profiles": []}}}) == []


def test_parse_desired_tolerates_bare_string_keys():
    """Hand-authored shadows may list bare S3-key strings (ADR-0002 v1 CLI/console);
    each normalizes to {"key": ...}."""
    doc = {"state": {"desired": {"profiles": ["profiles/x.json", "profiles/y.json"]}}}

    assert parse_desired(doc) == [
        {"key": "profiles/x.json"},
        {"key": "profiles/y.json"},
    ]


def test_parse_desired_drops_malformed_entries():
    """A typo'd entry (no usable key) is dropped, never fetched — the visible failure
    is simply that it doesn't appear in `reported`, not a crash."""
    doc = {
        "state": {
            "desired": {
                "profiles": [
                    {"key": "profiles/ok.json"},
                    {"nope": "no key here"},
                    None,
                    123,
                    "profiles/also-ok.json",
                ]
            }
        }
    }

    assert parse_desired(doc) == [
        {"key": "profiles/ok.json"},
        {"key": "profiles/also-ok.json"},
    ]


def test_offline_unavailable_desired_keeps_cache_intact(tmp_path):
    """desired=None means the assignment is UNAVAILABLE (shadow unreadable /
    offline). The cached set must be kept: nothing fetched, nothing deleted."""
    managed = tmp_path / "managed"
    managed.mkdir()
    (managed / "A.json").write_bytes(b"a")
    (managed / "B.json").write_bytes(b"b")
    fetches = []

    result = reconcile(None, managed, fetch=lambda key: fetches.append(key) or b"x")

    assert (managed / "A.json").exists()
    assert (managed / "B.json").exists()
    assert fetches == []
    assert {p["name"] for p in result.present} == {"A.json", "B.json"}


def test_fetch_failure_is_non_fatal_and_preserves_cache(tmp_path):
    """A failed S3 fetch for one key must not crash reconcile, delete cached
    profiles, or block other keys — the failure is surfaced in errors and
    retried next reconcile."""
    managed = tmp_path / "managed"
    managed.mkdir()
    (managed / "Have.json").write_bytes(b"have")  # already cached

    def fetch(key):
        if key.endswith("Bad.json"):
            raise RuntimeError("s3 unreachable")
        return b"good"

    result = reconcile(
        [
            {"key": "profiles/Have.json"},
            {"key": "profiles/Bad.json"},
            {"key": "profiles/Good.json"},
        ],
        managed,
        fetch,
    )

    assert (managed / "Have.json").read_bytes() == b"have"   # cache preserved
    assert (managed / "Good.json").read_bytes() == b"good"   # others still sync
    assert not (managed / "Bad.json").exists()               # failed one skipped
    assert any(e["name"] == "Bad.json" for e in result.errors)


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
