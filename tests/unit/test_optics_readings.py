"""
Unit tests for optics_readings capture at run completion (#288).

Behaviors tested against the frozen device<->cloud contract
(AcornGenetics/acorn-analytics#45), asserted field-for-field against the
shared fixtures committed under tests/fixtures/optics/:

  1. A complete run builds a payload matching the frozen contract
  2. An aborted run with a partial capture -> complete=false, aborted=true
  3. An aborted run with no capture -> no event (None)
  4. expected_lines follows the frozen constant (read_passes x reads_per_cycle x 60)
"""
import base64
import gzip
from pathlib import Path

from aquila_web.optics_readings import (
    build_optics_readings,
    count_data_lines,
    expected_lines,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "optics"
SAMPLE_LOG = FIXTURES / "sample.log"          # baseline + 1 cycle, complete: 960 data rows
PARTIAL_LOG = FIXTURES / "partial.log"        # crashed mid-run: 480 of 960 data rows

# Frozen values from the shared contract fixtures.
SAMPLE_SHA256 = "1c5e37c5e8207b2d5efa2f8a9a3b411914393853220a1d476d97890c0032b023"
PARTIAL_SHA256 = "24f9bafcd5d7679a7991c991c90118f8438d43ea3e7815502793ca1c131086a7"
RUN_TIMESTAMP = "2026-03-13T10:35:40Z"


def test_complete_run_builds_frozen_contract_payload():
    payload = build_optics_readings(
        SAMPLE_LOG, run_timestamp=RUN_TIMESTAMP, expected_lines=960, aborted=False
    )
    assert payload["run_timestamp"] == RUN_TIMESTAMP
    assert payload["filename"] == "sample.log"
    assert payload["sha256"] == SAMPLE_SHA256
    assert payload["raw_bytes"] == 37942
    assert payload["line_count"] == 960
    assert payload["expected_lines"] == 960
    assert payload["complete"] is True
    assert payload["aborted"] is False
    assert payload["chunk_index"] == 0
    assert payload["chunk_count"] == 1
    # data_b64 round-trips back to the raw file bytes.
    assert gzip.decompress(base64.b64decode(payload["data_b64"])) == SAMPLE_LOG.read_bytes()


def test_aborted_run_with_partial_capture_is_incomplete():
    payload = build_optics_readings(
        PARTIAL_LOG, run_timestamp=RUN_TIMESTAMP, expected_lines=960, aborted=True
    )
    assert payload["filename"] == "partial.log"
    assert payload["sha256"] == PARTIAL_SHA256
    assert payload["raw_bytes"] == 19222
    assert payload["line_count"] == 480
    assert payload["expected_lines"] == 960
    assert payload["complete"] is False
    assert payload["aborted"] is True


def test_aborted_run_with_no_capture_emits_no_event(tmp_path):
    missing = tmp_path / "never_written.log"
    payload = build_optics_readings(
        missing, run_timestamp=RUN_TIMESTAMP, expected_lines=960, aborted=True
    )
    assert payload is None


def test_expected_lines_uses_frozen_constant():
    # read_passes = baseline + one per cycle; reads_per_cycle = 8 (rox+fam);
    # 60 = SAMPLES_PER_BLINK. A 40-cycle run => 41 passes => 19,680 data rows.
    assert expected_lines(read_passes=41, reads_per_cycle=8) == 19680
    # The shared sample fixture: baseline + 1 cycle = 2 passes => 960.
    assert expected_lines(read_passes=2, reads_per_cycle=8) == 960


def test_count_data_lines_excludes_header_and_missing_file(tmp_path):
    assert count_data_lines(SAMPLE_LOG) == 960          # excludes "# Starting optics log"
    assert count_data_lines(PARTIAL_LOG) == 480
    assert count_data_lines(tmp_path / "absent.log") == 0
