"""
Unit tests for the background sync task and manual flush endpoint.

Behaviors tested:
  1. POST /sync/flush syncs pending events and returns the count
  2. POST /sync/flush returns {"synced": 0} when no endpoint is configured
  3. Network errors are swallowed — flush returns {"synced": 0}, events stay pending
"""
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def db_client(tmp_path, monkeypatch):
    """TestClient with an isolated SQLite DB and a fake sync endpoint."""
    monkeypatch.setenv("AQ_LOCAL_DB_PATH", str(tmp_path / "test_sync.db"))
    from aquila_web import local_db, main as web_main
    local_db.init_local_db()
    with TestClient(web_main.app) as c:
        yield c, local_db


def _seed_event(local_db, tmp_path):
    """Insert one run_complete event so there is something to sync."""
    local_db.enqueue_event("run_complete", {"run_name": "Run 1", "profile": "p.json", "result": "ok"})


class TestClientCertificate:
    """Sync authenticates with the Device Certificate (mTLS), not x-api-key."""

    def test_presents_client_cert_and_sends_no_api_key(self, db_client, tmp_path, monkeypatch):
        client, local_db = db_client
        _seed_event(local_db, tmp_path)
        monkeypatch.setenv("AQ_SYNC_ENDPOINT", "http://fake-aws/ingest")
        monkeypatch.setenv("AQ_SYNC_CLIENT_CERT", "/opt/aquila/config/device.crt")
        monkeypatch.setenv("AQ_SYNC_CLIENT_KEY", "/opt/aquila/config/device.key")

        captured = {}

        class _OK:
            status_code = 200
            def raise_for_status(self): pass

        def _capture(*a, **kw):
            captured.update(kw)
            return _OK()

        monkeypatch.setattr("aquila_web.sync.requests.post", _capture)
        client.post("/sync/flush")

        # The client certificate tuple is presented for the mTLS handshake...
        assert captured["cert"] == (
            "/opt/aquila/config/device.crt",
            "/opt/aquila/config/device.key",
        )
        # ...and the retired Fleet API Key header is gone.
        assert "x-api-key" not in captured.get("headers", {})

    def test_lingering_api_key_env_var_is_ignored(self, db_client, tmp_path, monkeypatch):
        # A stale AQ_SYNC_API_KEY left in the environment must never resurrect
        # the retired header — the key model is gone, not merely defaulted off.
        client, local_db = db_client
        _seed_event(local_db, tmp_path)
        monkeypatch.setenv("AQ_SYNC_ENDPOINT", "http://fake-aws/ingest")
        monkeypatch.setenv("AQ_SYNC_API_KEY", "stale-fleet-key")

        captured = {}

        class _OK:
            status_code = 200
            def raise_for_status(self): pass

        def _capture(*a, **kw):
            captured.update(kw)
            return _OK()

        monkeypatch.setattr("aquila_web.sync.requests.post", _capture)
        client.post("/sync/flush")

        assert "x-api-key" not in captured.get("headers", {})


class TestSyncFlushEndpoint:
    """POST /sync/flush behaviour."""

    def test_syncs_pending_events_and_returns_count(self, db_client, tmp_path, monkeypatch):
        client, local_db = db_client
        _seed_event(local_db, tmp_path)
        monkeypatch.setenv("AQ_SYNC_ENDPOINT", "http://fake-aws/ingest")

        class _OK:
            status_code = 200
            def raise_for_status(self): pass

        monkeypatch.setattr("aquila_web.sync.requests.post", lambda *a, **kw: _OK())
        response = client.post("/sync/flush")
        assert response.status_code == 200
        assert response.json()["synced"] == 1

    def test_returns_zero_when_no_endpoint_configured(self, db_client, tmp_path, monkeypatch):
        client, local_db = db_client
        _seed_event(local_db, tmp_path)
        monkeypatch.delenv("AQ_SYNC_ENDPOINT", raising=False)
        response = client.post("/sync/flush")
        assert response.status_code == 200
        assert response.json()["synced"] == 0

    def test_network_error_swallowed_returns_zero(self, db_client, tmp_path, monkeypatch):
        import requests as _requests
        client, local_db = db_client
        _seed_event(local_db, tmp_path)
        monkeypatch.setenv("AQ_SYNC_ENDPOINT", "http://fake-aws/ingest")
        monkeypatch.setattr(
            "aquila_web.sync.requests.post",
            lambda *a, **kw: (_ for _ in ()).throw(_requests.exceptions.ConnectionError("offline")),
        )
        response = client.post("/sync/flush")
        assert response.status_code == 200
        assert response.json()["synced"] == 0
        # event must still be pending — not lost
        assert len(local_db.get_pending_events()) == 1


class TestMaxMessageBytesValidation:
    """AQ_SYNC_MAX_MESSAGE_BYTES is validated so a misconfigured value can't
    crash the flush or drive the cap negative and mass-quarantine every event."""

    CEILING = 256 * 1024

    @pytest.mark.parametrize("raw, expected", [
        (None, CEILING),          # unset -> the real SQS ceiling
        ("131072", 131072),       # a valid override is honoured
        ("abc", CEILING),         # non-numeric -> fall back, don't crash int()
        ("0", CEILING),           # zero leaves no room -> fall back
        ("-100", CEILING),        # negative would invert the guard -> fall back
        ("4096", 4096),           # a sane small cap is honoured
    ])
    def test_falls_back_to_ceiling_on_a_bad_value(self, monkeypatch, raw, expected):
        from aquila_web import sync
        if raw is None:
            monkeypatch.delenv("AQ_SYNC_MAX_MESSAGE_BYTES", raising=False)
        else:
            monkeypatch.setenv("AQ_SYNC_MAX_MESSAGE_BYTES", raw)
        assert sync._resolve_max_message_bytes("sentri-01") == expected

    def test_cap_just_above_the_envelope_falls_back_instead_of_quarantining_all(self, monkeypatch):
        # A cap only a few bytes above the envelope leaves near-zero room, so
        # every event would be marked oversized and the whole queue quarantined.
        # It must fall back to the ceiling, not be honoured.
        from aquila_web import sync
        from aquila_web.sync_batching import envelope_overhead_bytes
        tiny = envelope_overhead_bytes("sentri-01") + 1
        monkeypatch.setenv("AQ_SYNC_MAX_MESSAGE_BYTES", str(tiny))
        assert sync._resolve_max_message_bytes("sentri-01") == self.CEILING


class TestSizeAwareBatching:
    """Sync packs events into byte-capped batches under the SQS ceiling (#289)."""

    def _capture_posts(self, monkeypatch):
        bodies = []

        class _OK:
            status_code = 200
            def raise_for_status(self): pass

        def _post(url, json=None, **kw):
            bodies.append(json)
            return _OK()

        monkeypatch.setattr("aquila_web.sync.requests.post", _post)
        return bodies

    def test_events_span_multiple_posts_each_under_the_byte_cap(self, db_client, tmp_path, monkeypatch):
        import json as _json
        client, local_db = db_client
        # Five ~2 KB events with a small cap => several POSTs, not one.
        for i in range(5):
            local_db.enqueue_event("optics_readings", {"i": i, "pad": "x" * 2000})
        monkeypatch.setenv("AQ_SYNC_ENDPOINT", "http://fake-aws/ingest")
        monkeypatch.setenv("AQ_SYNC_DEVICE_ID", "sentri-01")
        cap = 4096
        monkeypatch.setenv("AQ_SYNC_MAX_MESSAGE_BYTES", str(cap))
        bodies = self._capture_posts(monkeypatch)

        response = client.post("/sync/flush")

        assert response.json()["synced"] == 5
        assert len(bodies) > 1  # did not cram everything into one oversized POST
        for body in bodies:
            assert len(_json.dumps(body).encode("utf-8")) <= cap
        assert local_db.get_pending_events() == []  # all delivered

    def test_oversized_unsplittable_event_is_quarantined_while_others_flush(self, db_client, tmp_path, monkeypatch):
        client, local_db = db_client
        healthy = local_db.enqueue_event("run_complete", {"ok": True})
        # A run_complete with no gzip blob to chunk, too big to POST even alone.
        poison = local_db.enqueue_event("run_complete", {"pad": "x" * 8000})
        monkeypatch.setenv("AQ_SYNC_ENDPOINT", "http://fake-aws/ingest")
        monkeypatch.setenv("AQ_SYNC_DEVICE_ID", "sentri-01")
        monkeypatch.setenv("AQ_SYNC_MAX_MESSAGE_BYTES", "4096")
        bodies = self._capture_posts(monkeypatch)

        response = client.post("/sync/flush")

        # Healthy event delivered; poison never POSTed.
        assert response.json()["synced"] == 1
        posted_ids = [e["id"] for b in bodies for e in b["events"]]
        assert posted_ids == [healthy]
        # Poison quarantined — retained, loud, out of the flush path (not dropped).
        assert local_db.get_pending_events() == []
        quarantined = local_db.get_quarantined_events()
        assert [e["id"] for e in quarantined] == [poison]
        assert quarantined[0]["quarantine_reason"]

    def test_network_failure_on_a_later_batch_keeps_earlier_batches_synced(self, db_client, tmp_path, monkeypatch):
        import requests as _requests
        client, local_db = db_client
        ids = [local_db.enqueue_event("optics_readings", {"i": i, "pad": "x" * 2000}) for i in range(5)]
        monkeypatch.setenv("AQ_SYNC_ENDPOINT", "http://fake-aws/ingest")
        monkeypatch.setenv("AQ_SYNC_DEVICE_ID", "sentri-01")
        monkeypatch.setenv("AQ_SYNC_MAX_MESSAGE_BYTES", "4096")

        calls = {"n": 0}
        posted_ids: list[int] = []

        class _OK:
            status_code = 200
            def raise_for_status(self): pass

        def _post(url, json=None, **kw):
            calls["n"] += 1
            if calls["n"] == 2:  # second batch: network drops
                raise _requests.exceptions.ConnectionError("offline")
            posted_ids.extend(e["id"] for e in json["events"])
            return _OK()

        monkeypatch.setattr("aquila_web.sync.requests.post", _post)
        response = client.post("/sync/flush")

        # Only the first batch's events are marked synced; the rest stay pending.
        synced = response.json()["synced"]
        assert synced == len(posted_ids)
        assert 0 < synced < 5
        still_pending = [e["id"] for e in local_db.get_pending_events()]
        assert sorted(posted_ids + still_pending) == sorted(ids)  # nothing lost or duplicated
        assert set(posted_ids).isdisjoint(still_pending)

    def test_oversized_optics_event_is_split_into_reassemblable_chunk_posts(self, db_client, tmp_path, monkeypatch):
        import base64 as _b64
        import gzip as _gzip
        import hashlib as _hashlib
        import json as _json
        import os as _os

        client, local_db = db_client
        # A #288-shaped optics event whose gzipped blob dwarfs the cap.
        raw = _os.urandom(30000)  # incompressible => stays large after gzip
        blob = _gzip.compress(raw)
        sha = _hashlib.sha256(raw).hexdigest()
        source = local_db.enqueue_event("optics_readings", {
            "run_timestamp": "2026-07-05T10:00:00Z",
            "filename": "big.log",
            "sha256": sha,
            "raw_bytes": len(raw),
            "line_count": 500,
            "expected_lines": 500,
            "complete": True,
            "aborted": False,
            "chunk_index": 0,
            "chunk_count": 1,
            "data_b64": _b64.b64encode(blob).decode("ascii"),
        })
        monkeypatch.setenv("AQ_SYNC_ENDPOINT", "http://fake-aws/ingest")
        monkeypatch.setenv("AQ_SYNC_DEVICE_ID", "sentri-01")
        cap = 4096
        monkeypatch.setenv("AQ_SYNC_MAX_MESSAGE_BYTES", str(cap))
        bodies = self._capture_posts(monkeypatch)

        response = client.post("/sync/flush")

        # The source event is accounted for and left neither pending nor quarantined.
        assert response.json()["synced"] == 1
        assert local_db.get_pending_events() == []
        assert local_db.get_quarantined_events() == []

        # Every POST is under the ceiling, and more than one was needed.
        for body in bodies:
            assert len(_json.dumps(body).encode("utf-8")) <= cap
        chunks = [e["payload"] for b in bodies for e in b["events"]]
        assert len(chunks) > 1
        # All chunks share one sha256 with contiguous ordering...
        assert {c["sha256"] for c in chunks} == {sha}
        assert sorted(c["chunk_index"] for c in chunks) == list(range(len(chunks)))
        assert all(c["chunk_count"] == len(chunks) for c in chunks)
        # ...and reassemble to the exact original gzipped blob (no loss/truncation).
        ordered = sorted(chunks, key=lambda c: c["chunk_index"])
        reassembled = b"".join(_b64.b64decode(c["data_b64"]) for c in ordered)
        assert reassembled == blob
        assert _gzip.decompress(reassembled) == raw
