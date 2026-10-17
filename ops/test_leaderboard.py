from ops.leaderboard import _metrics


def test_unit_return_is_fractional():
    m = _metrics([0.01, -0.02])
    assert m["net_unit_return"] == -0.01
    assert m["trades"] == 2
