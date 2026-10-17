from ops.runledger import reconcile
from pathlib import Path
import json


def test_reconcile_matches_engine(tmp_path):
    path = tmp_path / "run.json"
    path.write_text(json.dumps({
        "trades": [{"net": 0.5, "side": "long"}, {"net": -0.4, "side": "short"}],
        "engine_metrics": {"sum_unit_return": 0.1, "compounded_unit_equity": 0.9, "max_drawdown": 0.4},
    }))
    out = reconcile(path)
    assert out["status"] == "RECONCILED"
    assert abs(out["independent"]["compounded_unit_equity"] - 0.9) < 1e-12
