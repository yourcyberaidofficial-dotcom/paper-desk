"""Closed-bar and experiment schemas. No order types."""

from dataclasses import asdict, dataclass

@dataclass(frozen=True)
class Bar:
    symbol: str
    interval: str
    open_time_ms: int
    close_time_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: str

    def to_dict(self):
        return asdict(self)

@dataclass(frozen=True)
class CostPath:
    name: str
    fee_bps_per_side: float
    half_spread_bps: float
    extra_bars: int

COSTS = {
    "optimistic": CostPath("optimistic", 7.5, 1.0, 0),
    "base": CostPath("base", 10.0, 1.0, 0),
    "stress": CostPath("stress", 10.0, 5.0, 1),
}

SLEEVES = {
    "aggressive": {"risk": 0.01, "daily_loss": 0.03, "max_open": 0.04},
    "balanced": {"risk": 0.005, "daily_loss": 0.02, "max_open": 0.02},
    "defensive": {"risk": 0.0025, "daily_loss": 0.01, "max_open": 0.01},
}
