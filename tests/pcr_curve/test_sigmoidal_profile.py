from aq_curve.evaluator import check_sigmoidal_profile


def test_sigmoidal_profile(curve_data, curve):
    assert check_sigmoidal_profile(curve_data, curve)
