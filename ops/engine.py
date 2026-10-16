"""Paper engine. Enforces sleeve caps. Does not invent an edge."""

from desk.accounting import Book
from desk.fill import entry_fill
from desk.schema import COSTS

SLEEVES = ("aggressive", "balanced", "defensive")

class PaperEngine:
    def __init__(self, ledger, strategy):
        self.ledger = ledger
        self.strategy = strategy
        self.books = {name: Book(name) for name in SLEEVES}
        self.positions = {}

    def ingest_bar(self, symbol: str, bar, cost_name: str = "base"):
        plan = self.strategy.plan(symbol, [bar])
        self.ledger.append({"type": "plan", "symbol": symbol, "plan": plan, "strategy": self.strategy.name})
        signal = self.strategy.signal(symbol, [bar])
        if signal is None or plan == "WAIT":
            return {"action": "wait", "symbol": symbol}
        return self._propose(symbol, signal, cost_name)

    def snapshot(self) -> dict:
        return {
            "balances": self.ledger.balances(),
            "open_positions": {f"{s}:{sym}": p for (s, sym), p in self.positions.items()},
            "strategy": self.strategy.name,
            "strategy_version": self.strategy.version,
        }
