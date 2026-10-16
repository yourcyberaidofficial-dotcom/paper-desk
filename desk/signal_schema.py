"""Research-candidate signal schema. Not an approved production signal."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ResearchSignal:
    signal_id: str
    generation: str
    asset: str
    instrument: str
    direction: str  # LONG_BIAS, SHORT_BIAS, WAIT
    signal_class: str  # research_candidate
    data_ts_ms: int
    timeframe: str
    reason: str

    def to_dict(self) -> dict:
        return {
            "signal_id": self.signal_id,
            "generation": self.generation,
            "asset": self.asset,
            "instrument": self.instrument,
            "direction": self.direction,
            "signal_class": self.signal_class,
            "data_ts_ms": self.data_ts_ms,
            "timeframe": self.timeframe,
            "reason": self.reason,
            "approved": False,
        }
