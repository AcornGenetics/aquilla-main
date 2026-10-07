"""ADC health telemetry — RDY/stale signal as structured samples with a
run+position+time correlation key, kept out of logger.log (#528 / Phase C)."""
import json
import logging

import pytest

from aq_lib.adc_health_log import (
    ADC_HEALTH_LOGGER_NAME,
    configure_adc_health_logger,
    emit_adc_health_sample,
)


@pytest.mark.unit
def test_emit_adc_health_sample_shape_and_correlation_key(tmp_path):
    configure_adc_health_logger(log_dir=str(tmp_path))
    sample = emit_adc_health_sample(
        run_timestamp="2026-10-06T00:00:00Z",
        position=3,
        n_stale_frames=2,
        n_retries=5,
        n_failed_reads=1,
        n_unrepairable=0,
    )
    # correlation key: run + position + time (joins against homing samples by run+ts)
    assert sample["run_timestamp"] == "2026-10-06T00:00:00Z"
    assert sample["position"] == 3
    assert sample["ts"].endswith("Z")
    assert "id" in sample
    # the RDY/stale signal
    assert sample["n_stale_frames"] == 2
    assert sample["n_retries"] == 5
    assert sample["n_failed_reads"] == 1
    assert sample["n_unrepairable"] == 0
    # written as one JSON line to the dedicated log
    line = (tmp_path / "adc_health.log").read_text().strip()
    assert json.loads(line) == sample


@pytest.mark.unit
def test_adc_health_samples_stay_out_of_logger_log():
    # Dedicated logger must not propagate to the parent 'aquila' logger.
    assert logging.getLogger(ADC_HEALTH_LOGGER_NAME).propagate is False
