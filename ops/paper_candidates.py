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
            "kind": "paper_candidate",
            "eligible": True,
            "direction": state["direction"],
            "source_candle_close_ms": candle_close_ms,
            "entry": "next completed-candle open after the source close",
            "exit": "opposite band or 8 bars, whichever comes first",
            "sizing": "one unit notional",
            "fees_bps_per_fill": 11,
            "validated": False,
        })
    return out
