"""
Backwards-compatible wrappers for aq_curve.main.
All logic now lives in aq_curve.curve.Curve.
"""
import logging

from aq_curve.curve import Curve

logger = logging.getLogger("aquila")

# Module-level singleton for backwards compatibility
_curve = Curve()

# Re-export constants for any code that may reference them
src_basedir = _curve.src_basedir
cross_talk_matrix = _curve.cross_talk_matrix
thresholds = _curve.thresholds


def get_curve(run_id, dye, channel):
    """Get baseline-corrected curve for a given run, dye, and channel."""
    return _curve.get_curve(run_id, dye, channel)


def is_detected(run_id, well):
    """Check if target is detected in a given well."""
    return _curve.is_detected(run_id, well)


def results_to_json(raw_logfile, results_logfile):
    """Generate JSON results file from raw optics log."""
    return _curve.results_to_json(raw_logfile, results_logfile)


if __name__ == "__main__":
    pass
