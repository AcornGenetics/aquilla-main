from pcr_curve_tests.evaluator import check_no_late_drift


def test_no_late_drift(curve_data, curve):
    assert check_no_late_drift(curve_data, curve)
