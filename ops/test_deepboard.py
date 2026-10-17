from ops.deepboard import _metrics


def test_sum_and_compound_differ():
    m = _metrics([{"net": 0.1, "side": "long"}, {"net": -0.1, "side": "short"}])
    assert abs(m["sum_unit_return"]) < 1e-12
    assert m["compounded_unit_equity"] < 1
