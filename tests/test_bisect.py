from flarebisect.bisect import classify


def test_classify_clean_break():
    assert classify(good_rate=0.0, culprit_rate=1.0) == "clean break"


def test_classify_flakiness_regression():
    assert classify(good_rate=0.0, culprit_rate=0.5) == "flakiness regression"
