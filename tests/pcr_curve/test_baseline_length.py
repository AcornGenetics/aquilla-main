from aq_curve.evaluator import check_baseline_length


def test_baseline_length(curve_data, curve):
    assert check_baseline_length(curve_data, curve)
