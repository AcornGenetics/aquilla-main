from pcr_curve_tests.evaluator import check_threshold_oscillation


def test_threshold_oscillation(curve_data, curve):
    assert check_threshold_oscillation(curve_data, curve)
