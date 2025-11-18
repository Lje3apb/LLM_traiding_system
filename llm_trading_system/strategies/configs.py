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
    max_martingale_step: int = 10  # Maximum martingale step to prevent blowup
    max_position_size: float = 0.25  # Maximum position size as fraction (HIGH-1 fix)

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

    def __post_init__(self) -> None:
        """Validate configuration parameters."""
        # Validate pyramiding
        if self.pyramiding < 1:
            raise ValueError(f"pyramiding must be >= 1, got {self.pyramiding}")

        # Validate martingale parameters
        if self.use_martingale and self.martingale_mult < 1.0:
            raise ValueError(
                f"martingale_mult must be >= 1.0, got {self.martingale_mult}"
            )
        if self.max_martingale_step < 0:
            raise ValueError(
                f"max_martingale_step must be >= 0, got {self.max_martingale_step}"
            )

        # Validate max position size (HIGH-1 fix)
        if self.max_position_size <= 0 or self.max_position_size > 1.0:
            raise ValueError(
                f"max_position_size must be in (0, 1], got {self.max_position_size}"
            )

        # Validate base size
        if self.base_size <= 0 or self.base_size > 1.0:
            raise ValueError(f"base_size must be in (0, 1], got {self.base_size}")
        if self.base_position_pct is not None:
            if self.base_position_pct <= 0 or self.base_position_pct > 100:
                raise ValueError(
                    f"base_position_pct must be in (0, 100], got {self.base_position_pct}"
                )

        # Validate TP/SL percentages
        if self.use_tp_sl:
            if self.tp_long_pct <= 0:
                raise ValueError(f"tp_long_pct must be > 0, got {self.tp_long_pct}")
            if self.sl_long_pct <= 0:
                raise ValueError(f"sl_long_pct must be > 0, got {self.sl_long_pct}")
            if self.tp_short_pct <= 0:
                raise ValueError(f"tp_short_pct must be > 0, got {self.tp_short_pct}")
            if self.sl_short_pct <= 0:
                raise ValueError(f"sl_short_pct must be > 0, got {self.sl_short_pct}")

        # Validate time filter
        if self.time_filter_enabled:
            if not (0 <= self.time_filter_start_hour <= 23):
                raise ValueError(
                    f"time_filter_start_hour must be in [0, 23], got {self.time_filter_start_hour}"
                )
            if not (0 <= self.time_filter_end_hour <= 23):
                raise ValueError(
                    f"time_filter_end_hour must be in [0, 23], got {self.time_filter_end_hour}"
                )

        # Validate RSI thresholds
        if not (0 <= self.rsi_ovs <= 100):
            raise ValueError(f"rsi_ovs must be in [0, 100], got {self.rsi_ovs}")
        if not (0 <= self.rsi_ovb <= 100):
            raise ValueError(f"rsi_ovb must be in [0, 100], got {self.rsi_ovb}")
        if self.rsi_ovs >= self.rsi_ovb:
            raise ValueError(
                f"rsi_ovs must be < rsi_ovb, got ovs={self.rsi_ovs}, ovb={self.rsi_ovb}"
            )

        # Validate indicator lengths
        if self.ema_fast_len < 1:
            raise ValueError(f"ema_fast_len must be >= 1, got {self.ema_fast_len}")
        if self.ema_slow_len < 1:
            raise ValueError(f"ema_slow_len must be >= 1, got {self.ema_slow_len}")
        if self.rsi_len < 1:
            raise ValueError(f"rsi_len must be >= 1, got {self.rsi_len}")
        if self.bb_len < 1:
            raise ValueError(f"bb_len must be >= 1, got {self.bb_len}")
        if self.atr_len < 1:
            raise ValueError(f"atr_len must be >= 1, got {self.atr_len}")
        if self.vol_ma_len < 1:
            raise ValueError(f"vol_ma_len must be >= 1, got {self.vol_ma_len}")
        if self.adx_len < 1:
            raise ValueError(f"adx_len must be >= 1, got {self.adx_len}")

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


@dataclass
class LLMRegimeConfig:
    """Configuration for LLM regime analysis and position sizing.

    This config controls how often the LLM is queried for market regime
    assessment and how the regime multipliers (k_long/k_short) are applied.
    """

    # LLM refresh parameters
    horizon_bars: int = 48  # How often to query LLM (e.g., every 48 bars of 5m = 4 hours)
    base_size: float = 0.01  # Base position size for regime calculation
    k_max: float = 2.0  # Maximum multiplier for position sizing
    temperature: float = 0.1  # LLM temperature for regime evaluation

    # Market snapshot parameters
    horizon_hours: int = 4  # Forecast horizon in hours
    base_asset: str = "BTCUSDT"  # Asset for market snapshot

    # LLM client settings (optional overrides)
    llm_model: str | None = None  # Model name (e.g., "llama3.2", "gpt-4")
    llm_provider: str = "ollama"  # Provider: "ollama", "openai", etc.
    llm_base_url: str | None = None  # Override LLM API base URL
    llm_timeout: int = 60  # LLM request timeout in seconds

    # Regime filtering parameters
    min_prob_edge: float = 0.05  # Minimum |prob_bull - prob_bear| to apply multipliers
    min_confidence_scaling: bool = True  # Scale by confidence_level from LLM
    neutral_k: float = 0.5  # Multiplier to use in neutral regime

    # Snapshot data sources (toggles for live mode)
    use_binance_data: bool = True  # Fetch Binance market data
    use_onchain_data: bool = False  # Fetch on-chain metrics (slower)
    use_news_data: bool = False  # Fetch news sentiment (requires API keys)

    def __post_init__(self) -> None:
        """Validate configuration parameters."""
        if self.horizon_bars < 1:
            raise ValueError(f"horizon_bars must be >= 1, got {self.horizon_bars}")

        if self.base_size <= 0 or self.base_size > 1.0:
            raise ValueError(f"base_size must be in (0, 1], got {self.base_size}")

        if self.k_max < 1.0:
            raise ValueError(f"k_max must be >= 1.0, got {self.k_max}")

        if not (0.0 <= self.temperature <= 2.0):
            raise ValueError(f"temperature must be in [0, 2], got {self.temperature}")

        if self.horizon_hours < 1:
            raise ValueError(f"horizon_hours must be >= 1, got {self.horizon_hours}")

        if not (0.0 <= self.min_prob_edge <= 0.5):
            raise ValueError(
                f"min_prob_edge must be in [0, 0.5], got {self.min_prob_edge}"
            )

        if self.neutral_k < 0 or self.neutral_k > self.k_max:
            raise ValueError(
                f"neutral_k must be in [0, k_max], got {self.neutral_k} (k_max={self.k_max})"
            )

        if self.llm_timeout < 1:
            raise ValueError(f"llm_timeout must be >= 1, got {self.llm_timeout}")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LLMRegimeConfig:
        """Create config from dictionary, ignoring unknown keys.

        Args:
            data: Dictionary with configuration parameters

        Returns:
            LLMRegimeConfig instance
        """
        valid_fields = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)

    def to_dict(self) -> dict[str, Any]:
        """Convert config to a JSON-serializable dictionary.

        Returns:
            Dictionary with all configuration parameters
        """
        return asdict(self)


__all__ = ["IndicatorStrategyConfig", "LLMRegimeConfig"]
