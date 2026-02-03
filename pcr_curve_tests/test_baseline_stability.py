from pcr_curve_tests.evaluator import check_baseline_stability


def test_baseline_stability(curve_data, curve):
    assert check_baseline_stability(curve_data, curve)
