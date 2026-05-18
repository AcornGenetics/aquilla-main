from aq_curve.evaluator import check_monotonic_rise


def test_monotonic_rise(curve_data, curve):
    assert check_monotonic_rise(curve_data, curve)
