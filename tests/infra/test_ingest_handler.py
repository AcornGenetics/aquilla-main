"""
Unit tests for Lambda 1: ingest-handler.

Behaviors:
  1. Valid batch → messages sent to SQS, returns {"queued": N}
  2. Empty events list → 200, {"queued": 0}, no SQS messages
  3. Missing device_id → 400, no SQS messages
  4. Missing events key → 400, no SQS messages
"""
import json
import os
from unittest.mock import MagicMock, patch

import pytest

import ingest_handler


def _event(body: dict) -> dict:
    return {"body": json.dumps(body)}


@pytest.fixture(autouse=True)
def sqs_env(monkeypatch):
    monkeypatch.setenv("SQS_QUEUE_URL", "https://sqs.us-east-1.amazonaws.com/123/sentri-queue")


class TestIngestHandler:

    def test_valid_batch_returns_queued_count(self, monkeypatch):
        mock_sqs = MagicMock()
        monkeypatch.setattr("ingest_handler.boto3.client", lambda *a, **kw: mock_sqs)
        body = {
            "device_id": "abc123",
            "events": [
                {"id": 1, "event_type": "run_complete", "payload": {}},
                {"id": 2, "event_type": "run_complete", "payload": {}},
            ],
        }
        response = ingest_handler.handler(_event(body), {})
        assert response["statusCode"] == 200
        assert json.loads(response["body"])["queued"] == 2

    def test_valid_batch_sends_sqs_messages(self, monkeypatch):
        mock_sqs = MagicMock()
        monkeypatch.setattr("ingest_handler.boto3.client", lambda *a, **kw: mock_sqs)
        body = {
            "device_id": "abc123",
            "events": [{"id": 1, "event_type": "run_complete", "payload": {}}],
        }
        ingest_handler.handler(_event(body), {})
        assert mock_sqs.send_message.call_count == 1

    def test_empty_events_returns_zero(self, monkeypatch):
        mock_sqs = MagicMock()
        monkeypatch.setattr("ingest_handler.boto3.client", lambda *a, **kw: mock_sqs)
        body = {"device_id": "abc123", "events": []}
        response = ingest_handler.handler(_event(body), {})
        assert response["statusCode"] == 200
        assert json.loads(response["body"])["queued"] == 0
        mock_sqs.send_message.assert_not_called()

    def test_missing_device_id_returns_400(self, monkeypatch):
        mock_sqs = MagicMock()
        monkeypatch.setattr("ingest_handler.boto3.client", lambda *a, **kw: mock_sqs)
        body = {"events": [{"id": 1}]}
        response = ingest_handler.handler(_event(body), {})
        assert response["statusCode"] == 400
        mock_sqs.send_message.assert_not_called()

    def test_missing_events_key_returns_400(self, monkeypatch):
        mock_sqs = MagicMock()
        monkeypatch.setattr("ingest_handler.boto3.client", lambda *a, **kw: mock_sqs)
        body = {"device_id": "abc123"}
        response = ingest_handler.handler(_event(body), {})
        assert response["statusCode"] == 400
        mock_sqs.send_message.assert_not_called()
