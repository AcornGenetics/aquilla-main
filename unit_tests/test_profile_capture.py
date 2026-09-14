"""
Unit tests for aquila_web/profile_sync.capture_local_profile (issue #460).

When a Run uses a Local Profile — authored on-device, not in S3 — its body is
captured up to the versioned S3 bucket, content-addressed by canonical sha, so
a run's exact recipe is reconstructable from S3 uniformly with Managed Profiles
(ADR-0002). Managed Profiles are already in S3, so they are never re-uploaded.
The uploader is injected; the real boto3/S3 wiring is boundary glue tracked
separately.
"""
import json
from pathlib import Path

import pytest

from aquila_web.profile_sync import capture_local_profile
from aq_lib.profile_hash import canonical_profile_hash

pytestmark = pytest.mark.unit


def test_captures_a_local_profile_to_content_addressed_key(tmp_path):
    local = tmp_path / "local"
    local.mkdir()
    content = {"title": "MyLocal", "steps": [{"setpoint": 95, "duration": 1}]}
    path = local / "MyLocal.json"
    path.write_text(json.dumps(content))

    uploaded = {}
    result = capture_local_profile(path, local, upload=lambda key, body: uploaded.__setitem__(key, body))

    sha = canonical_profile_hash(content)
    hexpart = sha.split(":")[-1]
    assert result["sha256"] == sha
    assert result["key"] == f"profiles/captured/{hexpart}.json"
    assert uploaded[result["key"]] == path.read_bytes()


def test_managed_profile_is_not_captured(tmp_path):
    """Managed Profiles already live in S3 — capture must skip them (no upload,
    returns None)."""
    managed = tmp_path / "managed"
    managed.mkdir()
    local = tmp_path / "local"
    local.mkdir()
    path = managed / "Mgd.json"
    path.write_text(json.dumps({"title": "Mgd"}))

    calls = []
    result = capture_local_profile(path, local, upload=lambda key, body: calls.append(key))

    assert result is None
    assert calls == []


def test_capture_is_content_addressed_and_idempotent(tmp_path):
    """Re-running the same Local Profile targets the same content-addressed key
    (no duplicate object), and that key matches the run-record's profile_sha256
    so acorn-internal-app can fetch the recipe by the recorded hash."""
    local = tmp_path / "local"
    local.mkdir()
    content = {"title": "P", "steps": [{"setpoint": 60, "duration": 30}]}
    path = local / "P.json"
    path.write_text(json.dumps(content))

    keys = []
    upload = lambda key, body: keys.append(key)
    r1 = capture_local_profile(path, local, upload)
    r2 = capture_local_profile(path, local, upload)

    assert r1["key"] == r2["key"]
    assert len(set(keys)) == 1  # same key both runs — no duplicate object
    hexpart = canonical_profile_hash(content).split(":")[-1]
    assert r1["key"] == f"profiles/captured/{hexpart}.json"
    assert r1["sha256"] == f"canon-v1:sha256:{hexpart}"
