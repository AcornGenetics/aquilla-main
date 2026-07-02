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


class TestSizeAwareFlush:
    """Size-aware Sync (#289): byte-capped batching + oversized-event quarantine."""

    def test_events_over_cap_are_sent_in_separate_posts(self, db_client, tmp_path, monkeypatch):
        client, local_db = db_client
        # Two events, each ~600 bytes of payload, with a tiny message cap so they
        # cannot share one POST.
        local_db.enqueue_event("run_complete", {"blob": "a" * 600})
        local_db.enqueue_event("run_complete", {"blob": "b" * 600})
        monkeypatch.setenv("AQ_SYNC_ENDPOINT", "http://fake-aws/ingest")
        monkeypatch.setenv("AQ_SYNC_MAX_MESSAGE_BYTES", "900")

        posts = []

        class _OK:
            status_code = 200
            def raise_for_status(self): pass

        def _capture(*a, **kw):
            posts.append(kw.get("json"))
            return _OK()

        monkeypatch.setattr("aquila_web.sync.requests.post", _capture)
        response = client.post("/sync/flush")

        assert response.json()["synced"] == 2
        assert len(posts) == 2  # one event per POST — never bundled over the cap
        assert len(local_db.get_pending_events()) == 0

    def test_oversized_event_is_quarantined_and_rest_sync(self, db_client, tmp_path, monkeypatch):
        client, local_db = db_client
        healthy_id = local_db.enqueue_event("run_complete", {"blob": "a" * 100})
        poison_id = local_db.enqueue_event("optics_readings", {"blob": "z" * 5_000})
        monkeypatch.setenv("AQ_SYNC_ENDPOINT", "http://fake-aws/ingest")
        # Cap holds the healthy event but not the poison one (which can't be sent alone).
        monkeypatch.setenv("AQ_SYNC_MAX_MESSAGE_BYTES", "800")

        sent_ids = []

        class _OK:
            status_code = 200
            def raise_for_status(self): pass

        def _capture(*a, **kw):
            sent_ids.extend(e["id"] for e in kw["json"]["events"])
            return _OK()

        monkeypatch.setattr("aquila_web.sync.requests.post", _capture)
        response = client.post("/sync/flush")

        assert response.json()["synced"] == 1          # poison excluded from the count
        assert sent_ids == [healthy_id]                # only the healthy event went out
        # Poison is quarantined: no longer pending (frees its batch slot), but the
        # row is NOT dropped — it stays in the DB, visible for follow-up.
        pending_ids = [e["id"] for e in local_db.get_pending_events()]
        assert poison_id not in pending_ids
        assert local_db.get_quarantined_events()[0]["id"] == poison_id

    def test_quarantined_event_is_not_reprocessed_on_next_flush(self, db_client, tmp_path, monkeypatch):
        # A poison event must be logged/handled once, then left alone — never
        # re-fetched, re-serialized, or re-logged every interval (unbounded spam),
        # and never occupying a batch slot behind healthy events.
        client, local_db = db_client
        local_db.enqueue_event("optics_readings", {"blob": "z" * 5_000})
        monkeypatch.setenv("AQ_SYNC_ENDPOINT", "http://fake-aws/ingest")
        monkeypatch.setenv("AQ_SYNC_MAX_MESSAGE_BYTES", "800")

        posts = []

        class _OK:
            status_code = 200
            def raise_for_status(self): pass

        def _capture(*a, **kw):
            posts.append(kw.get("json"))
            return _OK()

        monkeypatch.setattr("aquila_web.sync.requests.post", _capture)
        client.post("/sync/flush")   # first flush quarantines it
        second = client.post("/sync/flush")   # second flush must ignore it entirely

        assert second.json()["synced"] == 0
        assert posts == []                     # nothing was ever POSTed across both flushes
        assert local_db.get_pending_events() == []  # not re-fetched as pending

    def test_event_just_under_the_true_ceiling_still_syncs(self, db_client, tmp_path, monkeypatch):
        # The batch cap must reserve only the ACTUAL envelope size, not a coarse
        # 4 KB guess. An event ~150 bytes under the 256 KB ceiling fits once the
        # real ~40-byte wrapper is accounted for; the old fixed reserve would have
        # wrongly quarantined it.
        from aquila_web import sync_batching
        client, local_db = db_client
        monkeypatch.setenv("AQ_SYNC_ENDPOINT", "http://fake-aws/ingest")
        monkeypatch.setenv("AQ_SYNC_DEVICE_ID", "dev-abc-123")
        # Size the payload so the event lands ~2 KB under the ceiling: above the
        # OLD 4 KB-reserve cap (would be quarantined) but genuinely fits once the
        # real ~40-byte wrapper is reserved.
        blob_len = sync_batching.MAX_MESSAGE_BYTES - 2_000
        event_id = local_db.enqueue_event("optics_readings", {"blob": "z" * blob_len})
        [pending] = local_db.get_pending_events()
        size = sync_batching.event_size_bytes(pending)
        old_reserve_cap = sync_batching.MAX_MESSAGE_BYTES - 4_096
        true_cap = sync_batching.max_batch_bytes("dev-abc-123", max_events=100)
        assert old_reserve_cap < size <= true_cap  # discriminates old vs new reserve

        sent_ids = []

        class _OK:
            status_code = 200
            def raise_for_status(self): pass

        def _capture(*a, **kw):
            sent_ids.extend(e["id"] for e in kw["json"]["events"])
            return _OK()

        monkeypatch.setattr("aquila_web.sync.requests.post", _capture)
        response = client.post("/sync/flush")

        assert response.json()["synced"] == 1        # fits — not needlessly quarantined
        assert sent_ids == [event_id]
        assert local_db.get_quarantined_events() == []

    def test_network_error_on_later_batch_keeps_earlier_batch_synced(self, db_client, tmp_path, monkeypatch):
        import requests as _requests
        client, local_db = db_client
        first_id = local_db.enqueue_event("run_complete", {"blob": "a" * 600})
        second_id = local_db.enqueue_event("run_complete", {"blob": "b" * 600})
        monkeypatch.setenv("AQ_SYNC_ENDPOINT", "http://fake-aws/ingest")
        monkeypatch.setenv("AQ_SYNC_MAX_MESSAGE_BYTES", "900")  # one event per POST

        calls = {"n": 0}

        class _OK:
            status_code = 200
            def raise_for_status(self): pass

        def _flaky(*a, **kw):
            calls["n"] += 1
            if calls["n"] == 2:  # second batch fails
                raise _requests.exceptions.ConnectionError("offline")
            return _OK()

        monkeypatch.setattr("aquila_web.sync.requests.post", _flaky)
        response = client.post("/sync/flush")

        assert response.json()["synced"] == 1                  # only the first batch
        pending_ids = [e["id"] for e in local_db.get_pending_events()]
        assert pending_ids == [second_id]                      # second stays pending
        assert first_id not in pending_ids                     # first was durably synced


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
