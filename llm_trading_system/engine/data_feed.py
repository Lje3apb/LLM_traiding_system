"""Historical data feed implementations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Protocol

from llm_trading_system.strategies.base import Bar


class HistoricalDataFeed(Protocol):
    """Protocol returning an iterator of historical bars."""

    def iter(self) -> Iterator[Bar]:  # pragma: no cover - interface only
        ...


@dataclass(slots=True)
class CSVDataFeed:
    """Simple CSV reader producing :class:`Bar` objects."""

    path: Path | str
    symbol: str
    tzinfo: datetime.tzinfo | None = None

    def iter(self) -> Iterator[Bar]:
        path = Path(self.path)
        with path.open("r", encoding="utf-8") as fh:
            header = fh.readline().strip().split(",")
            name_to_idx = {name: idx for idx, name in enumerate(header)}
            required = ["timestamp", "open", "high", "low", "close", "volume"]
            missing = [col for col in required if col not in name_to_idx]
            if missing:
                raise ValueError(f"CSV is missing required columns: {missing}")

            for line in fh:
                if not line.strip():
                    continue
                parts = line.strip().split(",")
                ts = parse_timestamp(parts[name_to_idx["timestamp"]], self.tzinfo)
                yield Bar(
                    timestamp=ts,
                    open=float(parts[name_to_idx["open"]]),
                    high=float(parts[name_to_idx["high"]]),
                    low=float(parts[name_to_idx["low"]]),
                    close=float(parts[name_to_idx["close"]]),
                    volume=float(parts[name_to_idx["volume"]]),
                )


def parse_timestamp(value: str, tzinfo: datetime.tzinfo | None) -> datetime:
    """Parse ISO8601 timestamps or unix seconds."""

    value = value.strip()
    if value.isdigit():
        ts = datetime.fromtimestamp(int(value), tz=timezone.utc)
    else:
        ts = datetime.fromisoformat(value)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=tzinfo or timezone.utc)
    if tzinfo:
        ts = ts.astimezone(tzinfo)
    return ts


__all__ = ["HistoricalDataFeed", "CSVDataFeed", "parse_timestamp"]
