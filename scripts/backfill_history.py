#!/usr/bin/env python3
"""
One-time backfill script: loads historical run results from logs/history.json
into the Sentri analytics pipeline via the API Gateway ingest endpoint.

Usage (run on device or locally with access to the results files):

    python scripts/backfill_history.py \
        --endpoint https://<id>.execute-api.us-east-2.amazonaws.com/prod/ingest \
        --api-key <fleet-key> \
        --device-id <rpi-serial> \
        --history /opt/aquila/logs/history.json \
        --results-dir /opt/aquila/logs/results

    # Dry run — prints events without sending
    python scripts/backfill_history.py ... --dry-run
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

_CHANNEL_MAP = {"1": "fam", "2": "rox"}


def _parse_calls(results: dict) -> list[dict]:
    """Transform a results JSON dict into a calls array."""
    calls = []
    cq_data = results.get("cq", {})
    for row_key, channel in _CHANNEL_MAP.items():
        row = results.get(row_key, {})
        cq_row = cq_data.get(row_key, {})
        if not isinstance(row, dict):
            continue
        for col_key, call_value in row.items():
            try:
                well = int(col_key)
            except ValueError:
                continue
            cq = cq_row.get(col_key)
            calls.append({
                "well": well,
                "channel": channel,
                "call": call_value,
                "cq": float(cq) if cq is not None else None,
            })
    return calls


def _parse_timestamp(ts_str: str) -> str:
    """Parse 'YYYY-MM-DD HH:MM' history timestamp to ISO-8601 UTC string."""
    try:
        dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M")
        return dt.replace(tzinfo=timezone.utc).isoformat()
    except (ValueError, TypeError):
        return datetime.now(timezone.utc).isoformat()


def _load_history(history_path: Path) -> list[dict]:
    with history_path.open() as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    # some versions wrap in {"history": [...]}
    if isinstance(data, dict) and "history" in data:
        return data["history"]
    return []


def _build_events(history: list[dict], results_dir: Path) -> list[dict]:
    events = []
    for idx, entry in enumerate(history):
        results_path_str = entry.get("results_path")
        if not results_path_str:
            continue

        # Try absolute path first, then relative to results_dir
        results_path = Path(results_path_str)
        if not results_path.exists():
            results_path = results_dir / results_path.name
        if not results_path.exists():
            print(f"  SKIP [{idx}] results file not found: {results_path_str}", file=sys.stderr)
            continue

        try:
            with results_path.open() as f:
                results_data = json.load(f)
        except Exception as e:
            print(f"  SKIP [{idx}] could not read {results_path}: {e}", file=sys.stderr)
            continue

        calls = _parse_calls(results_data)
        if not calls:
            print(f"  SKIP [{idx}] no calls parsed from {results_path.name}", file=sys.stderr)
            continue

        profile = entry.get("profile") or ""
        run_name = entry.get("run_name") or ""
        run_timestamp = _parse_timestamp(entry.get("timestamp", ""))

        events.append({
            "id": idx,
            "event_type": "run_complete",
            "created_at": run_timestamp,
            "payload": {
                "profile": profile,
                "run_name": run_name,
                "run_timestamp": run_timestamp,
                "duration_seconds": None,
                "aborted": False,
                "calls": calls,
            },
        })

    return events


def _post_batch(endpoint: str, api_key: str, device_id: str, events: list[dict]) -> int:
    headers = {"Content-Type": "application/json", "x-api-key": api_key}
    payload = {"device_id": device_id, "events": events}
    resp = requests.post(endpoint, json=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json().get("queued", len(events))


def main():
    parser = argparse.ArgumentParser(description="Backfill historical run results to Aurora")
    parser.add_argument("--endpoint", default=os.getenv("AQ_SYNC_ENDPOINT"), required=False)
    parser.add_argument("--api-key", default=os.getenv("AQ_SYNC_API_KEY"), required=False)
    parser.add_argument("--device-id", default=os.getenv("AQ_SYNC_DEVICE_ID") or os.getenv("DEVICE_ID"))
    parser.add_argument("--history", type=Path, default=Path("/opt/aquila/logs/history.json"))
    parser.add_argument("--results-dir", type=Path, default=Path("/opt/aquila/logs/results"))
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.dry_run:
        if not args.endpoint:
            sys.exit("Error: --endpoint or AQ_SYNC_ENDPOINT required")
        if not args.api_key:
            sys.exit("Error: --api-key or AQ_SYNC_API_KEY required")
        if not args.device_id:
            sys.exit("Error: --device-id or AQ_SYNC_DEVICE_ID required")

    if not args.history.exists():
        sys.exit(f"Error: history file not found: {args.history}")

    print(f"Loading history from {args.history}")
    history = _load_history(args.history)
    print(f"Found {len(history)} history entries")

    events = _build_events(history, args.results_dir)
    print(f"Built {len(events)} events from results files")

    if args.dry_run:
        print("\n--- DRY RUN ---")
        for evt in events[:5]:
            print(json.dumps(evt, indent=2))
        if len(events) > 5:
            print(f"... and {len(events) - 5} more")
        return

    total_queued = 0
    for i in range(0, len(events), args.batch_size):
        batch = events[i:i + args.batch_size]
        queued = _post_batch(args.endpoint, args.api_key, args.device_id, batch)
        total_queued += queued
        print(f"  Sent batch {i // args.batch_size + 1}: {queued} events queued")
        if i + args.batch_size < len(events):
            time.sleep(1)  # avoid rate limiting

    print(f"\nDone. {total_queued} events queued for processing.")


if __name__ == "__main__":
    main()
