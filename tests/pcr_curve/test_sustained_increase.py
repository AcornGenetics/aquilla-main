from aq_curve.evaluator import check_sustained_increase


def test_sustained_increase(curve_data, curve):
    assert check_sustained_increase(curve_data, curve)
