from flarebisect.bisect import classify, status_label


def test_classify_clean_break():
    assert classify(good_rate=0.0, culprit_rate=1.0) == "clean break"


def test_classify_flakiness_regression():
    assert classify(good_rate=0.0, culprit_rate=0.5) == "flakiness regression"


def test_status_label_culprit_wins_over_last():
    # a commit can be both the bisected culprit and the last commit in range
    assert status_label(0.8, is_first=False, is_last=True, is_culprit=True) == "flare"


def test_status_label_bad_endpoint_not_culprit():
    assert status_label(0.2, is_first=False, is_last=True, is_culprit=False) == "bad"


def test_status_label_good_baseline():
    assert status_label(0.0, is_first=True, is_last=False, is_culprit=False) == "good"


def test_status_label_stable_midrange():
    assert status_label(0.0, is_first=False, is_last=False, is_culprit=False) == "stable"


def test_status_label_wobbling_midrange():
    assert status_label(0.2, is_first=False, is_last=False, is_culprit=False) == "wobbling"
