"""Unit tests for the on-device Managed Profile sync agent (issue #465).

ProfileSyncAgent wires the tested decisions (parse_desired + reconcile) to
Greengrass Core IPC + S3: read the `profiles` shadow's desired, reconcile the
local managed/ dir, write the result to the shadow's reported. The IPC client and
the S3 fetch are injected, so the orchestration is testable with fakes — the real
greengrasscoreipc/boto3 adapters are thin glue verified on-device (like
start_update_agent). Marked ``unit``.
"""
import pytest

pytestmark = pytest.mark.unit

from aquila_web.profile_sync_agent import ProfileSyncAgent


class FakeIpc:
    """Records reported writes; returns a canned `profiles` shadow document."""

    def __init__(self, shadow_doc):
        self._shadow_doc = shadow_doc
        self.reported = []

    def get_thing_shadow(self, shadow_name):
        assert shadow_name == "profiles"
        return self._shadow_doc

    def update_thing_shadow(self, payload, shadow_name):
        self.reported.append((shadow_name, payload))


def test_sync_once_materializes_desired_profile_and_reports_it(tmp_path):
    """The tracer: a profile assigned in the shadow is fetched from S3, written into
    managed/, and echoed back into the shadow's reported."""
    managed = tmp_path / "managed"
    doc = {"state": {"desired": {"profiles": [{"key": "profiles/x.json"}]}}}
    ipc = FakeIpc(doc)
    fetched = []

    def fetch(key):
        fetched.append(key)
        return b'{"title": "x"}'

    agent = ProfileSyncAgent(ipc, managed, fetch)

    agent.sync_once()

    assert (managed / "x.json").read_bytes() == b'{"title": "x"}'
    assert fetched == ["profiles/x.json"]
    assert ipc.reported == [
        ("profiles", {"profiles": [{"name": "x.json", "version": None}]})
    ]


def test_sync_once_unavailable_shadow_keeps_cache_and_reports_it(tmp_path):
    """No readable shadow → reconcile no-ops (keeps the cached managed/ set); the
    agent still reports what's on disk and never fetches."""
    managed = tmp_path / "managed"
    managed.mkdir()
    (managed / "cached.json").write_bytes(b"c")
    ipc = FakeIpc(None)

    def fetch(key):
        raise AssertionError("must not fetch when the assignment is unavailable")

    agent = ProfileSyncAgent(ipc, managed, fetch)

    agent.sync_once()

    assert (managed / "cached.json").exists()
    assert ipc.reported == [
        ("profiles", {"profiles": [{"name": "cached.json", "version": None}]})
    ]
