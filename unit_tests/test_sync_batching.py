"""
Unit tests for aquila_web/sync_batching.py — size-aware Sync (issue #289).

Pure logic, no IO: pack outbox events into byte-capped batches so a large
optics payload never pushes a POST past the SQS 256 KB message limit, guard
against a single oversized event, and split an over-limit gzipped log into
ordered chunks sharing one sha256.
"""
import base64
import json

from aquila_web import sync_batching


def _event(event_id: int, payload: dict) -> dict:
    """A minimal outbox event row as get_pending_events() returns it."""
    return {
        "id": event_id,
        "event_type": "run_complete",
        "payload": payload,
        "device_id": "dev-1",
        "created_at": "2026-07-02T00:00:00Z",
    }


class TestBatchEvents:
    def test_small_events_pack_into_one_batch(self):
        events = [_event(i, {"n": i}) for i in range(3)]
        batches = sync_batching.batch_events(events, max_bytes=1_000_000)
        assert len(batches) == 1
        assert [e["id"] for e in batches[0]] == [0, 1, 2]

    def test_events_over_cap_split_into_multiple_batches(self):
        events = [_event(i, {"n": i}) for i in range(4)]
        one = sync_batching.event_size_bytes(events[0])
        # A cap that holds two events but not three forces >1 batch.
        cap = one * 2 + 1
        batches = sync_batching.batch_events(events, max_bytes=cap)
        assert len(batches) > 1
        for batch in batches:
            assert sum(sync_batching.event_size_bytes(e) for e in batch) <= cap

    def test_large_optics_event_is_sent_alone(self):
        small_a = _event(1, {"n": 1})
        small_b = _event(3, {"n": 3})
        optics = {
            "id": 2,
            "event_type": "optics_readings",
            "payload": {"data": "x" * 10_000},  # a big blob relative to the small events
            "device_id": "dev-1",
            "created_at": "2026-07-02T00:00:00Z",
        }
        # Cap comfortably holds the two small events together, but not with optics.
        cap = sync_batching.event_size_bytes(optics) + 10
        batches = sync_batching.batch_events([small_a, optics, small_b], max_bytes=cap)
        optics_batches = [b for b in batches if any(e["id"] == 2 for e in b)]
        assert len(optics_batches) == 1
        assert [e["id"] for e in optics_batches[0]] == [2]  # alone in its own POST

    def test_id_order_is_preserved_across_batches(self):
        events = [_event(i, {"n": i}) for i in range(6)]
        cap = sync_batching.event_size_bytes(events[0]) * 2 + 1
        batches = sync_batching.batch_events(events, max_bytes=cap)
        flattened = [e["id"] for batch in batches for e in batch]
        assert flattened == [0, 1, 2, 3, 4, 5]


class TestSizeGuard:
    def test_partitions_oversized_from_fittable(self):
        small_a = _event(1, {"n": 1})
        small_b = _event(3, {"n": 3})
        poison = _event(2, {"blob": "x" * 5_000})
        cap = sync_batching.event_size_bytes(poison) - 1  # poison can't fit alone

        ok, oversized = sync_batching.partition_oversized(
            [small_a, poison, small_b], max_bytes=cap
        )

        assert [e["id"] for e in ok] == [1, 3]        # healthy events, order kept
        assert [e["id"] for e in oversized] == [2]    # poison quarantined out


class TestEnvelopeOverhead:
    def test_overhead_is_the_measured_wrapper_not_a_coarse_reserve(self):
        # The reserve must be the actual {device_id, events:[]} wrapper (tens of
        # bytes), never a fat fixed headroom that quarantines near-ceiling events.
        overhead = sync_batching.envelope_overhead_bytes("dev-abc-123", max_events=1)
        empty = {"device_id": "dev-abc-123", "events": []}
        assert overhead == len(json.dumps(empty).encode("utf-8"))
        assert overhead < 100  # far tighter than the old 4096-byte reserve

    def test_overhead_reserves_one_separator_per_extra_event(self):
        one = sync_batching.envelope_overhead_bytes("d", max_events=1)
        many = sync_batching.envelope_overhead_bytes("d", max_events=10)
        assert many - one == 9  # 9 commas between 10 events

    def test_max_batch_bytes_leaves_the_ceiling_minus_overhead(self):
        cap = sync_batching.max_batch_bytes("d", message_ceiling=1000, max_events=1)
        assert cap == 1000 - sync_batching.envelope_overhead_bytes("d", 1)


class TestSplitLog:
    def test_blob_under_limit_is_a_single_chunk(self):
        blob = b"gzipped-optics-log-bytes"
        chunks = sync_batching.split_log(blob, sha256="abc123", max_chunk_bytes=1_000_000)
        assert len(chunks) == 1
        chunk = chunks[0]
        assert chunk["chunk_index"] == 0
        assert chunk["chunk_count"] == 1
        assert chunk["sha256"] == "abc123"
        assert base64.b64decode(chunk["data"]) == blob

    def test_blob_over_limit_splits_into_ordered_chunks(self):
        blob = bytes(range(256)) * 20  # 5120 bytes of varied content
        cap = 512  # per-chunk base64 data cap, forces several chunks
        chunks = sync_batching.split_log(blob, sha256="deadbeef", max_chunk_bytes=cap)

        assert len(chunks) > 1
        # ordered 0..n-1
        assert [c["chunk_index"] for c in chunks] == list(range(len(chunks)))
        # every chunk agrees on the total and the shared integrity hash
        assert all(c["chunk_count"] == len(chunks) for c in chunks)
        assert all(c["sha256"] == "deadbeef" for c in chunks)
        # every chunk's payload respects the cap
        assert all(len(c["data"]) <= cap for c in chunks)
        # concatenating decoded chunks in order reconstructs the blob exactly
        reassembled = b"".join(base64.b64decode(c["data"]) for c in chunks)
        assert reassembled == blob
