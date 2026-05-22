from aq_curve.evaluator import check_log_phase_linearity


def test_log_phase_linearity(curve_data, curve):
    assert check_log_phase_linearity(curve_data, curve)
