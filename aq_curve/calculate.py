"""
Backwards-compatible wrappers for aq_curve.calculate.
All logic now lives in aq_curve.curve.Curve.
"""
from aq_curve.curve import Curve

# Module-level singleton for backwards compatibility
_curve = Curve()


def reject_outliers(data, m=2.0):
    """Filter outliers from data array."""
    return Curve._reject_outliers(data, m)


def load_data(basedir, fname):
    """Load data from file. Note: basedir is ignored, uses singleton's basedir."""
    temp_curve = Curve(src_basedir=basedir)
    return temp_curve._load_data(fname)


def extract_data(basedir, logfilename, dye, well):
    """Extract fluorescence data for a given dye and well."""
    temp_curve = Curve(src_basedir=basedir)
    return temp_curve.extract_data(logfilename, dye, well)


def baseline(xdata, ydata):
    """Calculate baseline for a curve."""
    return _curve.baseline(xdata, ydata)
