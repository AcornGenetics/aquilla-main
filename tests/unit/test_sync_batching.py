"""
Unit tests for size-aware Sync batching (#289).

Pure logic (no IO): pack pending Events into byte-capped batches under the SQS
256 KB ceiling, partition events too large to fit even alone, and split an
over-ceiling gzipped optics log into ordered chunks sharing one sha256.

Behaviors are asserted through the public interface of aquila_web.sync_batching
so they survive internal refactors.
"""
import base64
import json

from aquila_web.sync_batching import (
    batch_events,
    envelope_overhead_bytes,
    event_size_bytes,
    partition_oversized,
    split_log,
)


def _reassemble(chunks: list[dict]) -> bytes:
    ordered = sorted(chunks, key=lambda c: c["chunk_index"])
    return b"".join(base64.b64decode(c["data_b64"]) for c in ordered)


def _event(event_id: int, payload: dict) -> dict:
    return {
        "id": event_id,
        "event_type": "optics_readings",
        "payload": payload,
        "device_id": "sentri-01",
        "created_at": "2026-07-05T10:00:00Z",
    }


class TestEventSizeBytes:
    def test_measures_the_serialized_json_byte_length_of_one_event(self):
        event = _event(1, {"line_count": 960})
        # The event contributes exactly its JSON serialization to the POST body.
        assert event_size_bytes(event) == len(json.dumps(event).encode("utf-8"))


class TestEnvelopeOverheadBytes:
    def test_measures_the_empty_wrapper_around_the_events_array(self):
        # The POST body is {"device_id": ..., "events": [...]}; the wrapper's
        # fixed cost must be reserved from the cap so a full batch + wrapper fits.
        wrapper = {"device_id": "sentri-01", "events": []}
        assert envelope_overhead_bytes("sentri-01") == len(
            json.dumps(wrapper).encode("utf-8")
        )

    def test_is_device_aware(self):
        # A longer device_id means a larger wrapper -> less room for events.
        assert envelope_overhead_bytes("a-much-longer-device-id") > envelope_overhead_bytes("x")


class TestBatchEvents:
    def test_events_that_fit_pack_into_one_ordered_batch(self):
        # Well under the cap: everything rides in a single POST, order preserved.
        events = [_event(i, {"n": i}) for i in range(1, 6)]
        batches = batch_events(events, cap=256 * 1024, device_id="sentri-01")
        assert len(batches) == 1
        assert [e["id"] for e in batches[0]] == [1, 2, 3, 4, 5]

    def test_events_spill_into_multiple_ordered_batches_each_under_cap(self):
        device = "sentri-01"
        events = [_event(i, {"n": i}) for i in range(1, 7)]  # uniform size (1 digit)
        per = event_size_bytes(events[0])
        # Cap leaves room for ~2 events per batch beyond the wrapper.
        cap = envelope_overhead_bytes(device) + 2 * per + 4
        batches = batch_events(events, cap=cap, device_id=device)
        assert len(batches) > 1
        # Every batch, serialized as a real POST body, stays under the cap.
        for batch in batches:
            body = json.dumps({"device_id": device, "events": batch}).encode("utf-8")
            assert len(body) <= cap
        # No event is dropped or reordered across the spill.
        assert [e["id"] for b in batches for e in b] == [1, 2, 3, 4, 5, 6]

    def test_maximally_packed_batch_never_serializes_past_the_cap(self):
        # Regression: json.dumps inserts a 2-byte ", " between array items. With
        # many small events in one batch those separators add up; if they are not
        # reserved, a full batch serializes past the SQS ceiling and SQS silently
        # rejects the message. Every produced batch must fit as a real POST body.
        device = "sentri-01"
        cap = 256 * 1024
        events = [_event(i, {"n": i, "pad": "x" * 100}) for i in range(2000)]
        batches = batch_events(events, cap=cap, device_id=device)
        assert len(batches) > 1  # enough events to fill more than one batch
        for batch in batches:
            body = json.dumps({"device_id": device, "events": batch}).encode("utf-8")
            assert len(body) <= cap


class TestPartitionOversized:
    def test_event_too_large_to_fit_even_alone_is_separated_out(self):
        device = "sentri-01"
        cap = 1024
        small = [_event(1, {"n": 1}), _event(2, {"n": 2})]
        huge = _event(3, {"blob": "x" * 4000})  # exceeds cap even by itself
        assert event_size_bytes(huge) + envelope_overhead_bytes(device) > cap

        syncable, oversized = partition_oversized(small + [huge], cap=cap, device_id=device)

        assert [e["id"] for e in syncable] == [1, 2]
        assert [e["id"] for e in oversized] == [3]

    def test_all_events_syncable_when_none_exceeds_the_cap(self):
        device = "sentri-01"
        events = [_event(i, {"n": i}) for i in range(1, 4)]
        syncable, oversized = partition_oversized(events, cap=256 * 1024, device_id=device)
        assert [e["id"] for e in syncable] == [1, 2, 3]
        assert oversized == []


class TestSplitLog:
    SHA = "1c5e37c5e8207b2d5efa2f8a9a3b411914393853220a1d476d97890c0032b023"

    def test_blob_within_the_limit_stays_a_single_chunk(self):
        blob = b"gzipped-optics-bytes"
        chunks = split_log(blob, sha256=self.SHA, max_chunk_bytes=1024)
        assert len(chunks) == 1
        assert chunks[0]["chunk_index"] == 0
        assert chunks[0]["chunk_count"] == 1
        assert chunks[0]["sha256"] == self.SHA
        assert _reassemble(chunks) == blob

    def test_over_limit_blob_splits_into_ordered_chunks_sharing_one_sha256(self):
        blob = bytes(range(256)) * 40  # 10_240 bytes of varied content
        max_chunk = 1000
        chunks = split_log(blob, sha256=self.SHA, max_chunk_bytes=max_chunk)

        assert len(chunks) == 11  # ceil(10240 / 1000)
        # Contiguous, zero-based ordering and a consistent chunk_count.
        assert [c["chunk_index"] for c in chunks] == list(range(11))
        assert all(c["chunk_count"] == 11 for c in chunks)
        # One sha256 shared across every chunk (the logical-file identity).
        assert {c["sha256"] for c in chunks} == {self.SHA}
        # No raw slice exceeds the limit.
        assert all(len(base64.b64decode(c["data_b64"])) <= max_chunk for c in chunks)
        # Reassembling the chunks in order reproduces the blob byte-for-byte.
        assert _reassemble(chunks) == blob
