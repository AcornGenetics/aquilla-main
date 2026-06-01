from aq_curve.evaluator import check_threshold_oscillation


def test_threshold_oscillation(curve_data, curve):
    assert check_threshold_oscillation(curve_data, curve)
