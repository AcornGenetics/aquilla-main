from aq_curve.evaluator import check_signal_range


def test_signal_range(curve_data, curve):
    assert check_signal_range(curve_data, curve)
