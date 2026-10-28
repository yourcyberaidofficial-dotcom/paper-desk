"""Paper candidates only for strategies with complete rules."""


def candidates(states, symbol, candle_close_ms):
    out = []
    for state in states:
        if state["strategy"] != "E1-donchian-20" or state["direction"] == "WAIT":
            out.append({
                "strategy": state["strategy"],
                "kind": "research_observation",
                "eligible": False,
                "missing": "no complete entry/exit/sizing rule" if state["strategy"] != "E1-donchian-20" else "no directional trigger",
            })
            continue
        out.append({
            "strategy": state["strategy"],
            "symbol": symbol,
            "kind": "research_observation",
            "eligible": False,
            "direction": state["direction"],
            "source_candle_close_ms": candle_close_ms,
            "missing": "benchmark_failed",
            "validated": False,
        })
    return out
