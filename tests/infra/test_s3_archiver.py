"""
Unit tests for Lambda 2: s3-archiver.

Behaviors:
  1. Single SQS record → one S3 object at correct path {date}/{device_id}/{event_id}.json
  2. Batch of N records → N S3 put_object calls
  3. S3 error → exception propagates (triggers SQS retry)
"""
import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, call

import pytest

import s3_archiver


@pytest.fixture(autouse=True)
def s3_env(monkeypatch):
    monkeypatch.setenv("S3_BUCKET", "sentri-raw-events")


def _sqs_event(records: list[dict]) -> dict:
    return {
        "Records": [
            {"body": json.dumps(r)} for r in records
        ]
    }


def _record(device_id="dev1", event_id=42):
    return {
        "device_id": device_id,
        "event": {"id": event_id, "event_type": "run_complete", "payload": {}},
    }


class TestS3Archiver:

    def test_single_record_puts_to_correct_s3_path(self, monkeypatch):
        mock_s3 = MagicMock()
        monkeypatch.setattr("s3_archiver.boto3.client", lambda *a, **kw: mock_s3)
        fixed_date = "2026-06-10"
        monkeypatch.setattr(
            "s3_archiver.datetime",
            type("_FakeDT", (), {"now": staticmethod(lambda tz=None: datetime(2026, 6, 10, tzinfo=timezone.utc))})(),
        )
        s3_archiver.handler(_sqs_event([_record("dev1", 42)]), {})
        mock_s3.put_object.assert_called_once()
        kwargs = mock_s3.put_object.call_args.kwargs
        assert kwargs["Bucket"] == "sentri-raw-events"
        assert kwargs["Key"] == f"{fixed_date}/dev1/42.json"

    def test_batch_of_n_records_produces_n_s3_objects(self, monkeypatch):
        mock_s3 = MagicMock()
        monkeypatch.setattr("s3_archiver.boto3.client", lambda *a, **kw: mock_s3)
        records = [_record("dev1", i) for i in range(5)]
        s3_archiver.handler(_sqs_event(records), {})
        assert mock_s3.put_object.call_count == 5

    def test_s3_error_propagates(self, monkeypatch):
        mock_s3 = MagicMock()
        mock_s3.put_object.side_effect = RuntimeError("S3 unavailable")
        monkeypatch.setattr("s3_archiver.boto3.client", lambda *a, **kw: mock_s3)
        with pytest.raises(RuntimeError, match="S3 unavailable"):
            s3_archiver.handler(_sqs_event([_record()]), {})
