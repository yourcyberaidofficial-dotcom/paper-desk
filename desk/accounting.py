"""Sleeve accounting and combined crypto open-risk bucket."""

from desk.schema import SLEEVES

class Book:
    def __init__(self, sleeve: str, balance: float = 10_000.0):
        if sleeve not in SLEEVES:
            raise ValueError(sleeve)
        self.sleeve = sleeve
        self.caps = SLEEVES[sleeve]
        self.balance = balance
        self.open_risk = {}
        self.day_loss = 0.0

    def units(self, distance: float):
        if distance is None or distance <= 0:
            return 0.0
        return (self.balance * self.caps["risk"]) / distance

    def can_open(self, symbol: str, risk_amount: float) -> bool:
        if risk_amount <= 0:
            return False
        if self.day_loss >= self.balance * self.caps["daily_loss"]:
            return False
        crypto = sum(value for key, value in self.open_risk.items() if key in {"BTCUSDT", "ETHUSDT"})
        if symbol in {"BTCUSDT", "ETHUSDT"} and crypto + risk_amount > self.balance * self.caps["max_open"] + 1e-9:
            return False
        if symbol not in {"BTCUSDT", "ETHUSDT"}:
            return False
        return True

    def open_position(self, symbol: str, risk_amount: float):
        self.open_risk[symbol] = risk_amount
