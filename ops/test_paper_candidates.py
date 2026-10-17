from ops.paper_candidates import candidates


def test_bias_is_not_a_candidate():
    out = candidates([{"strategy": "SMA20-state", "direction": "LONG_BIAS"}], "BTCUSDT", 1)
    assert out[0]["eligible"] is False


def test_e1_direction_is_a_candidate():
    out = candidates([{"strategy": "E1-donchian-20", "direction": "SHORT_BIAS"}], "BTCUSDT", 1)
    assert out[0]["eligible"] is True
    assert out[0]["entry"].startswith("next")
