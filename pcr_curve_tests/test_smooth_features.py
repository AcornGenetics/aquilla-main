from aq_curve.evaluator import check_smooth_features


def test_smooth_features(curve_data, curve):
    assert check_smooth_features(curve_data, curve)
