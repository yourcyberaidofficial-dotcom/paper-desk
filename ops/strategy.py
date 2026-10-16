"""Strategy interface. Default emits WAIT. No edge is assumed."""

class WaitStrategy:
    name = "wait-default"
    version = "0"

    def plan(self, symbol: str, bars) -> str:
        return "WAIT"

    def signal(self, symbol: str, bars):
        return None
