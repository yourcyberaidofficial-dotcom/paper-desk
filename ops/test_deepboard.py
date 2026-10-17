from ops.deepboard import _metrics

def test_positive_sum_can_lose_compounded_equity():
    trades = [{"net": 0.50, "side": "long"}, {"net": -0.40, "side": "short"}]
    m = _metrics(trades)
    assert abs(m["sum_unit_return"] - 0.10) < 1e-12
    assert abs(m["compounded_unit_equity"] - 0.90) < 1e-12
    assert m["max_drawdown"] > 0
