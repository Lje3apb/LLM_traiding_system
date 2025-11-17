"""Configuration objects for trading strategies."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any

from llm_trading_system.strategies.modes import StrategyMode


@dataclass
class IndicatorStrategyConfig:
    """Configuration for indicator-based (quantitative) trading strategies.

    This config supports PineScript-style technical indicator parameters
    and can be used in QUANT_ONLY or HYBRID strategy modes.
    """

    mode: StrategyMode = StrategyMode.QUANT_ONLY
    symbol: str = "BTCUSDT"

    # EMA parameters
    ema_fast_len: int = 50
    ema_slow_len: int = 200

    # ADX (Average Directional Index) parameters
    use_adx: bool = True
    adx_len: int = 14
    adx_threshold: int = 20

    # RSI (Relative Strength Index) parameters
    rsi_len: int = 14
    rsi_ovb: int = 70  # overbought threshold
    rsi_ovs: int = 30  # oversold threshold

    # Bollinger Bands parameters
    bb_len: int = 20
    bb_mult: float = 2.0

    # Volume parameters
    vol_ma_len: int = 20
    use_volume_confirm: bool = True

    # ATR (Average True Range) parameters for stops/targets
    atr_len: int = 14
    atr_stop_mult: float = 1.5
    atr_tp_mult: float = 2.8

    # Position control
    allow_long: bool = True
    allow_short: bool = True
    base_size: float = 0.01  # Base position size as fraction of equity

    # Pyramiding and martingale parameters (TradingView-style)
    base_position_pct: float | None = None  # Base position % of equity for first entry
    pyramiding: int = 1  # Maximum number of pyramid entries
    use_martingale: bool = False  # Enable martingale scaling
    martingale_mult: float = 1.0  # Martingale multiplier (1.0 = no martingale)

    # Take Profit / Stop Loss parameters (percentage-based)
    tp_long_pct: float = 2.0  # Take profit for long positions (%)
    sl_long_pct: float = 2.0  # Stop loss for long positions (%)
    tp_short_pct: float = 2.0  # Take profit for short positions (%)
    sl_short_pct: float = 2.0  # Stop loss for short positions (%)
    use_tp_sl: bool = False  # Enable TP/SL functionality

    # Time filter parameters
    time_filter_enabled: bool = False  # Enable time-based filtering
    time_filter_start_hour: int = 0  # Start hour (0-23)
    time_filter_end_hour: int = 23  # End hour (0-23)

    # Volume filter multiplier
    vol_mult: float = 1.0  # Multiplier for volume MA comparison

    # LLM-related fields (for HYBRID and LLM_ONLY modes)
    k_max: float = 2.0  # Maximum LLM multiplier
    llm_horizon_hours: int | None = None  # Override snapshot horizon_hours
    llm_min_prob_edge: float = 0.05  # Minimal |prob_bull - prob_bear| for gating
    llm_min_trend_strength: float = 0.2  # Minimal trend_strength for multipliers
    llm_refresh_interval_bars: int = 30  # How often to refresh LLM regime in HYBRID

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IndicatorStrategyConfig:
        """Create config from dictionary, ignoring unknown keys.

        Args:
            data: Dictionary with configuration parameters

        Returns:
            IndicatorStrategyConfig instance
        """
        # Get valid field names for this dataclass
        valid_fields = {f.name for f in fields(cls)}

        # Filter to only known fields
        filtered = {k: v for k, v in data.items() if k in valid_fields}

        # Handle StrategyMode enum conversion if needed
        if "mode" in filtered and isinstance(filtered["mode"], str):
            filtered["mode"] = StrategyMode(filtered["mode"])

        return cls(**filtered)

    def to_dict(self) -> dict[str, Any]:
        """Convert config to a JSON-serializable dictionary.

        Returns:
            Dictionary with all configuration parameters
        """
        result = asdict(self)

        # Convert enum to its value for serialization
        if isinstance(result.get("mode"), StrategyMode):
            result["mode"] = result["mode"].value

        return result


__all__ = ["IndicatorStrategyConfig"]
