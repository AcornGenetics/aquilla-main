from aq_curve.evaluator import check_cycle_location


def test_cycle_location(curve_data, curve):
    assert check_cycle_location(curve_data, curve)
