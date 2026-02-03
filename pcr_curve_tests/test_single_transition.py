from aq_curve.evaluator import check_single_transition


def test_single_transition(curve_data, curve):
    assert check_single_transition(curve_data, curve)
