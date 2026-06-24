"""
Unit tests for Lambda 3: aurora-loader.

Behaviors:
  1. Valid S3 event → devices upserted, run inserted, run_results inserted
  2. Aborted run → runs row inserted with aborted=True, zero run_results inserts
  3. Duplicate event → handler completes without error (ON CONFLICT handled by DB)
  4. DB connection error → exception propagates (triggers S3 retry)
"""
import json
import sys
from unittest.mock import MagicMock, call, patch

import pytest

import aurora_loader


def _s3_event(bucket="sentri-raw-events", key="2026-06-10/dev1/42.json") -> dict:
    return {
        "Records": [
            {
                "s3": {
                    "bucket": {"name": bucket},
                    "object": {"key": key},
                }
            }
        ]
    }


def _s3_body(device_id="dev1", aborted=False, num_calls=2) -> dict:
    calls = [
        {"well": i + 1, "channel": "fam", "call": "Detected", "cq": 22.5}
        for i in range(num_calls)
    ]
    return {
        "device_id": device_id,
        "event": {
            "id": 42,
            "event_type": "run_complete",
            "created_at": "2026-06-10T12:00:00Z",
            "payload": {
                "profile": "basic_pcr.json",
                "run_name": "Run 1",
                "aborted": aborted,
                "calls": [] if aborted else calls,
            },
        },
    }


@pytest.fixture(autouse=True)
def db_env(monkeypatch):
    monkeypatch.setenv("DB_DSN", "postgresql://user:pass@localhost/sentri")


def _make_mocks(monkeypatch, body: dict):
    """Wire boto3 S3 mock and psycopg mock, return the cursor mock."""
    mock_s3 = MagicMock()
    mock_s3.get_object.return_value = {
        "Body": MagicMock(read=lambda: json.dumps(body).encode())
    }
    monkeypatch.setattr("aurora_loader.boto3.client", lambda *a, **kw: mock_s3)

    mock_cur = MagicMock()
    mock_conn = MagicMock()
    mock_conn.__enter__ = lambda s: mock_conn
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    import aurora_loader as _mod
    _mod.psycopg.connect.return_value = mock_conn

    return mock_cur


class TestAuroraLoader:

    def test_valid_event_executes_device_run_and_results_inserts(self, monkeypatch):
        body = _s3_body(num_calls=2)
        mock_cur = _make_mocks(monkeypatch, body)
        aurora_loader.handler(_s3_event(), {})
        # device upsert + run insert + 2 result inserts = at least 3 executes
        assert mock_cur.execute.call_count >= 3

    def test_aborted_run_skips_run_results(self, monkeypatch):
        body = _s3_body(aborted=True, num_calls=0)
        mock_cur = _make_mocks(monkeypatch, body)
        aurora_loader.handler(_s3_event(), {})
        # device upsert + run insert only = exactly 2 executes
        assert mock_cur.execute.call_count == 2

    def test_db_error_propagates(self, monkeypatch):
        body = _s3_body()
        _make_mocks(monkeypatch, body)
        import aurora_loader as _mod
        _mod.psycopg.connect.side_effect = RuntimeError("DB unavailable")
        with pytest.raises(RuntimeError, match="DB unavailable"):
            aurora_loader.handler(_s3_event(), {})
        _mod.psycopg.connect.side_effect = None  # reset for other tests

    def test_duplicate_event_does_not_raise(self, monkeypatch):
        body = _s3_body(num_calls=2)
        mock_cur = _make_mocks(monkeypatch, body)
        # Second call — cursor execute is idempotent (ON CONFLICT DO NOTHING in real DB)
        aurora_loader.handler(_s3_event(), {})
        aurora_loader.handler(_s3_event(), {})
        # No exception raised; execute was called both times
        assert mock_cur.execute.call_count >= 6
