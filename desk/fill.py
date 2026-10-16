"""Shared economic fill. Venue-agnostic."""

from dataclasses import dataclass

@dataclass(frozen=True)
class Fill:
    price: float
    fee: float
    path_unidentified: bool
    filled: bool

def _spread(price: float, half_spread_bps: float, side: int) -> float:
    adjustment = price * half_spread_bps / 10_000
    return price + adjustment if side > 0 else price - adjustment

def entry_fill(next_bar, side: int, cost) -> Fill:
    if next_bar is None or side == 0:
        return Fill(0.0, 0.0, False, False)
    price = _spread(next_bar.open, cost.half_spread_bps, side)
    fee = abs(price) * cost.fee_bps_per_side / 10_000
    return Fill(price, fee, False, True)
