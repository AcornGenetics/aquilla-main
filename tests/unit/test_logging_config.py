"""Pure-logic checks on LOGGING_CONFIG.

#517 Slice 1: adc_class.py and melt_curve.py log via getLogger("aquila_logger"),
a separate top-level name from "aquila". Without its own entry in LOGGING_CONFIG
it has no handler and falls through to root, so its messages go only to stdout
(docker logs) and never reach logs/logger.log. These tests pin the fix.
"""

from aq_lib.utils import LOGGING_CONFIG


def test_aquila_logger_is_configured():
    assert "aquila_logger" in LOGGING_CONFIG["loggers"]


def test_aquila_logger_writes_to_the_same_file_handler_as_aquila():
    aquila_logger = LOGGING_CONFIG["loggers"]["aquila_logger"]
    aquila = LOGGING_CONFIG["loggers"]["aquila"]
    # Same file handler so ADC-health logs land in logs/logger.log alongside the
    # main app log, not just stdout.
    assert aquila_logger["handlers"] == aquila["handlers"] == ["file"]
    assert LOGGING_CONFIG["handlers"]["file"]["filename"] == "logs/logger.log"


def test_aquila_logger_level_is_debug():
    assert LOGGING_CONFIG["loggers"]["aquila_logger"]["level"] == "DEBUG"
