from aq_curve.evaluator import check_threshold_crossing


def test_threshold_crossing(curve_data, curve):
    assert check_threshold_crossing(curve_data, curve)
