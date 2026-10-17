from ops.signals import research_states


def test_states_are_independent():
    bars = [{"high": 10, "low": 9, "close": 9.5} for _ in range(20)]
    bars.append({"high": 12, "low": 11, "close": 11})
    states = research_states(bars)
    names = [s["strategy"] for s in states]
    assert names == ["E1-donchian-20", "SMA20-state", "RSI14-state"]
    assert states[0]["direction"] == "LONG_BIAS"
    assert all(s["validated"] is False for s in states)
