"""Technical indicators for trading strategies."""

from __future__ import annotations

from collections import deque
from typing import Sequence


# ============================================================================
# Batch indicator functions
# ============================================================================


def sma(values: Sequence[float], length: int) -> float | None:
    """Calculate Simple Moving Average.

    Args:
        values: Price data (oldest first)
        length: Period for the moving average

    Returns:
        SMA value or None if insufficient data
    """
    if length <= 0 or len(values) < length:
        return None
    return sum(values[-length:]) / length


def ema(values: Sequence[float], length: int) -> float | None:
    """Calculate Exponential Moving Average.

    Args:
        values: Price data (oldest first)
        length: Period for the moving average

    Returns:
        EMA value or None if insufficient data
    """
    if length <= 0 or len(values) < length:
        return None

    k = 2.0 / (length + 1)
    ema_val = sum(values[:length]) / length  # Start with SMA

    for price in values[length:]:
        ema_val = price * k + ema_val * (1 - k)

    return ema_val


def rsi(values: Sequence[float], length: int = 14) -> float | None:
    """Calculate Relative Strength Index.

    Args:
        values: Price data (oldest first)
        length: Period for RSI calculation

    Returns:
        RSI value (0-100) or None if insufficient data
    """
    if length <= 0 or len(values) < length + 1:
        return None

    # Calculate price changes
    changes = [values[i] - values[i - 1] for i in range(1, len(values))]

    if len(changes) < length:
        return None

    # Separate gains and losses
    gains = [max(c, 0.0) for c in changes[-length:]]
    losses = [max(-c, 0.0) for c in changes[-length:]]

    avg_gain = sum(gains) / length
    avg_loss = sum(losses) / length

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    rs = avg_gain / avg_loss
    rsi_val = 100.0 - (100.0 / (1.0 + rs))

    return rsi_val


def macd(
    values: Sequence[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[float | None, float | None, float | None]:
    """Calculate MACD (Moving Average Convergence Divergence).

    Args:
        values: Price data (oldest first)
        fast: Fast EMA period
        slow: Slow EMA period
        signal: Signal line EMA period

    Returns:
        Tuple of (macd_line, signal_line, histogram) or (None, None, None)
    """
    if slow <= 0 or fast <= 0 or signal <= 0:
        return None, None, None

    if len(values) < slow:
        return None, None, None

    fast_ema = ema(values, fast)
    slow_ema = ema(values, slow)

    if fast_ema is None or slow_ema is None:
        return None, None, None

    macd_line = fast_ema - slow_ema

    # Calculate MACD history to compute signal line
    # We need enough data to calculate signal EMA
    if len(values) < slow + signal - 1:
        return macd_line, None, None

    # Build MACD history
    macd_history = []
    for i in range(slow, len(values) + 1):
        f_ema = ema(values[:i], fast)
        s_ema = ema(values[:i], slow)
        if f_ema is not None and s_ema is not None:
            macd_history.append(f_ema - s_ema)

    if len(macd_history) < signal:
        return macd_line, None, None

    signal_line = ema(macd_history, signal)
    histogram = macd_line - signal_line if signal_line is not None else None

    return macd_line, signal_line, histogram


def atr(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    length: int = 14,
) -> float | None:
    """Calculate Average True Range.

    Args:
        highs: High prices (oldest first)
        lows: Low prices (oldest first)
        closes: Close prices (oldest first)
        length: Period for ATR calculation

    Returns:
        ATR value or None if insufficient data
    """
    if length <= 0 or len(highs) < length + 1:
        return None

    if len(highs) != len(lows) or len(highs) != len(closes):
        return None

    # Calculate True Range for each bar
    true_ranges = []
    for i in range(1, len(highs)):
        high_low = highs[i] - lows[i]
        high_close = abs(highs[i] - closes[i - 1])
        low_close = abs(lows[i] - closes[i - 1])
        tr = max(high_low, high_close, low_close)
        true_ranges.append(tr)

    if len(true_ranges) < length:
        return None

    # ATR is the moving average of true range
    return sum(true_ranges[-length:]) / length


def bollinger(
    values: Sequence[float],
    length: int = 20,
    mult: float = 2.0,
) -> tuple[float | None, float | None, float | None]:
    """Calculate Bollinger Bands.

    Args:
        values: Price data (oldest first)
        length: Period for moving average and std dev
        mult: Standard deviation multiplier

    Returns:
        Tuple of (middle, upper, lower) or (None, None, None)
    """
    if length <= 0 or len(values) < length:
        return None, None, None

    middle = sma(values, length)
    if middle is None:
        return None, None, None

    # Calculate standard deviation
    recent = values[-length:]
    variance = sum((x - middle) ** 2 for x in recent) / length
    std_dev = variance**0.5

    upper = middle + mult * std_dev
    lower = middle - mult * std_dev

    return middle, upper, lower


def adx(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    length: int = 14,
) -> float | None:
    """Calculate Average Directional Index (simplified version).

    Args:
        highs: High prices (oldest first)
        lows: Low prices (oldest first)
        closes: Close prices (oldest first)
        length: Period for ADX calculation

    Returns:
        ADX value (0-100) or None if insufficient data
    """
    if length <= 0 or len(highs) < length * 2:
        return None

    if len(highs) != len(lows) or len(highs) != len(closes):
        return None

    # Calculate directional movement
    plus_dm = []
    minus_dm = []
    true_ranges = []

    for i in range(1, len(highs)):
        high_diff = highs[i] - highs[i - 1]
        low_diff = lows[i - 1] - lows[i]

        # +DM and -DM
        if high_diff > low_diff and high_diff > 0:
            plus_dm.append(high_diff)
        else:
            plus_dm.append(0.0)

        if low_diff > high_diff and low_diff > 0:
            minus_dm.append(low_diff)
        else:
            minus_dm.append(0.0)

        # True Range
        high_low = highs[i] - lows[i]
        high_close = abs(highs[i] - closes[i - 1])
        low_close = abs(lows[i] - closes[i - 1])
        true_ranges.append(max(high_low, high_close, low_close))

    if len(plus_dm) < length:
        return None

    # Smooth the values
    smoothed_plus_dm = sum(plus_dm[-length:]) / length
    smoothed_minus_dm = sum(minus_dm[-length:]) / length
    smoothed_tr = sum(true_ranges[-length:]) / length

    if smoothed_tr == 0:
        return 0.0

    # Calculate DI+ and DI-
    plus_di = 100 * smoothed_plus_dm / smoothed_tr
    minus_di = 100 * smoothed_minus_dm / smoothed_tr

    # Calculate DX
    di_sum = plus_di + minus_di
    if di_sum == 0:
        return 0.0

    dx = 100 * abs(plus_di - minus_di) / di_sum

    # ADX is typically the EMA of DX, but for simplicity we return DX
    # A full implementation would smooth this further
    return dx


# ============================================================================
# Stateful wrappers for streaming/incremental updates
# ============================================================================


class SMAState:
    """Stateful Simple Moving Average calculator for streaming data."""

    def __init__(self, length: int) -> None:
        """Initialize SMA state.

        Args:
            length: Period for the moving average
        """
        if length <= 0:
            raise ValueError("length must be positive")
        self.length = length
        self.values: deque[float] = deque(maxlen=length)

    def update(self, price: float) -> float | None:
        """Update with new price and return current SMA.

        Args:
            price: New price value

        Returns:
            SMA value or None if insufficient data
        """
        self.values.append(price)
        if len(self.values) < self.length:
            return None
        return sum(self.values) / self.length

    def reset(self) -> None:
        """Reset the state."""
        self.values.clear()


class EMAState:
    """Stateful Exponential Moving Average calculator for streaming data."""

    def __init__(self, length: int) -> None:
        """Initialize EMA state.

        Args:
            length: Period for the moving average
        """
        if length <= 0:
            raise ValueError("length must be positive")
        self.length = length
        self.k = 2.0 / (length + 1)
        self.ema_value: float | None = None
        self.warmup_values: list[float] = []

    def update(self, price: float) -> float | None:
        """Update with new price and return current EMA.

        Args:
            price: New price value

        Returns:
            EMA value or None if insufficient data
        """
        if self.ema_value is None:
            # Still warming up
            self.warmup_values.append(price)
            if len(self.warmup_values) >= self.length:
                # Initialize EMA with SMA
                self.ema_value = sum(self.warmup_values) / self.length
                self.warmup_values.clear()
                return self.ema_value
            return None
        else:
            # Update EMA
            self.ema_value = price * self.k + self.ema_value * (1 - self.k)
            return self.ema_value

    def reset(self) -> None:
        """Reset the state."""
        self.ema_value = None
        self.warmup_values.clear()


class RSIState:
    """Stateful RSI calculator for streaming data."""

    def __init__(self, length: int = 14) -> None:
        """Initialize RSI state.

        Args:
            length: Period for RSI calculation
        """
        if length <= 0:
            raise ValueError("length must be positive")
        self.length = length
        self.prev_price: float | None = None
        self.gains: deque[float] = deque(maxlen=length)
        self.losses: deque[float] = deque(maxlen=length)

    def update(self, price: float) -> float | None:
        """Update with new price and return current RSI.

        Args:
            price: New price value

        Returns:
            RSI value (0-100) or None if insufficient data
        """
        if self.prev_price is None:
            self.prev_price = price
            return None

        change = price - self.prev_price
        self.prev_price = price

        self.gains.append(max(change, 0.0))
        self.losses.append(max(-change, 0.0))

        if len(self.gains) < self.length:
            return None

        avg_gain = sum(self.gains) / self.length
        avg_loss = sum(self.losses) / self.length

        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0

        rs = avg_gain / avg_loss
        rsi_val = 100.0 - (100.0 / (1.0 + rs))

        return rsi_val

    def reset(self) -> None:
        """Reset the state."""
        self.prev_price = None
        self.gains.clear()
        self.losses.clear()


class ATRState:
    """Stateful ATR calculator for streaming data."""

    def __init__(self, length: int = 14) -> None:
        """Initialize ATR state.

        Args:
            length: Period for ATR calculation
        """
        if length <= 0:
            raise ValueError("length must be positive")
        self.length = length
        self.prev_close: float | None = None
        self.true_ranges: deque[float] = deque(maxlen=length)

    def update(self, high: float, low: float, close: float) -> float | None:
        """Update with new bar and return current ATR.

        Args:
            high: High price
            low: Low price
            close: Close price

        Returns:
            ATR value or None if insufficient data
        """
        if self.prev_close is None:
            self.prev_close = close
            return None

        high_low = high - low
        high_close = abs(high - self.prev_close)
        low_close = abs(low - self.prev_close)
        tr = max(high_low, high_close, low_close)

        self.true_ranges.append(tr)
        self.prev_close = close

        if len(self.true_ranges) < self.length:
            return None

        return sum(self.true_ranges) / self.length

    def reset(self) -> None:
        """Reset the state."""
        self.prev_close = None
        self.true_ranges.clear()


class BollingerState:
    """Stateful Bollinger Bands calculator for streaming data."""

    def __init__(self, length: int = 20, mult: float = 2.0) -> None:
        """Initialize Bollinger Bands state.

        Args:
            length: Period for moving average and std dev
            mult: Standard deviation multiplier
        """
        if length <= 0:
            raise ValueError("length must be positive")
        self.length = length
        self.mult = mult
        self.values: deque[float] = deque(maxlen=length)

    def update(
        self, price: float
    ) -> tuple[float | None, float | None, float | None]:
        """Update with new price and return current Bollinger Bands.

        Args:
            price: New price value

        Returns:
            Tuple of (middle, upper, lower) or (None, None, None)
        """
        self.values.append(price)

        if len(self.values) < self.length:
            return None, None, None

        middle = sum(self.values) / self.length
        variance = sum((x - middle) ** 2 for x in self.values) / self.length
        std_dev = variance**0.5

        upper = middle + self.mult * std_dev
        lower = middle - self.mult * std_dev

        return middle, upper, lower

    def reset(self) -> None:
        """Reset the state."""
        self.values.clear()


__all__ = [
    # Batch functions
    "sma",
    "ema",
    "rsi",
    "macd",
    "atr",
    "bollinger",
    "adx",
    # Stateful classes
    "SMAState",
    "EMAState",
    "RSIState",
    "ATRState",
    "BollingerState",
]
