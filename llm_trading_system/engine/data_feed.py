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

            for line_num, line in enumerate(fh, start=2):  # start=2 because header is line 1
                if not line.strip():
                    continue
                parts = line.strip().split(",")

                # Validate row has enough columns
                max_idx = max(name_to_idx.values())
                if len(parts) <= max_idx:
                    # Skip malformed line with warning
                    import warnings
                    warnings.warn(
                        f"Skipping malformed line {line_num} in {path}: "
                        f"expected {max_idx + 1} columns, got {len(parts)}"
                    )
                    continue

                # Parse values with error handling
                try:
                    ts = parse_timestamp(parts[name_to_idx["timestamp"]], self.tzinfo)
                    yield Bar(
                        timestamp=ts,
                        open=float(parts[name_to_idx["open"]]),
                        high=float(parts[name_to_idx["high"]]),
                        low=float(parts[name_to_idx["low"]]),
                        close=float(parts[name_to_idx["close"]]),
                        volume=float(parts[name_to_idx["volume"]]),
                    )
                except (ValueError, IndexError) as e:
                    # Skip line with invalid numeric values
                    import warnings
                    warnings.warn(
                        f"Skipping invalid data on line {line_num} in {path}: {e}"
                    )
                    continue


def parse_timestamp(value: str, tzinfo: datetime.tzinfo | None) -> datetime:
    """Parse ISO8601 timestamps, unix seconds, or milliseconds.

    Supports:
    - Unix timestamps in seconds: "1234567890"
    - Unix timestamps in milliseconds: "1234567890123"
    - Float timestamps: "1234567890.123"
    - ISO8601 strings: "2023-01-01T00:00:00Z"

    Args:
        value: Timestamp string
        tzinfo: Target timezone (default: UTC)

    Returns:
        Parsed datetime with timezone
    """
    value = value.strip()

    # Try parsing as numeric timestamp (int or float)
    try:
        timestamp = float(value)
        # If timestamp > 1e10, assume milliseconds
        if timestamp > 1e10:
            timestamp /= 1000.0
        ts = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    except ValueError:
        # Parse as ISO8601 string
        cleaned = value
        if cleaned.endswith("Z") or cleaned.endswith("z"):
            cleaned = cleaned[:-1] + "+00:00"
        ts = datetime.fromisoformat(cleaned)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=tzinfo or timezone.utc)

    # Convert to target timezone if specified
    if tzinfo:
        ts = ts.astimezone(tzinfo)
    return ts


__all__ = ["HistoricalDataFeed", "CSVDataFeed", "parse_timestamp"]
