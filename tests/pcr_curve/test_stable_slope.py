from aq_curve.evaluator import check_stable_slope


def test_stable_slope(curve_data, curve):
    assert check_stable_slope(curve_data, curve)
