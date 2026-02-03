from aq_curve.evaluator import check_baseline_stability


def test_baseline_stability(curve_data, curve):
    assert check_baseline_stability(curve_data, curve)
