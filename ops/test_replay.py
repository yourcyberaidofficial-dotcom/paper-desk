from ops.replay import _outcome


def test_wait_is_flat():
    out = _outcome({"strategy": "x", "direction": "WAIT"}, {"close": 1}, [{"open": 1, "close": 2, "close_time_ms": 1}])
    assert out["action"] == "flat"
    assert out["net"] == 0.0


def test_long_uses_next_open():
    after = [{"open": 10, "close": 11, "close_time_ms": 1}]
    out = _outcome({"strategy": "x", "direction": "LONG_BIAS"}, {"close": 9}, after)
    assert out["entry_price"] == 10
    assert out["net"] < out["gross"]
