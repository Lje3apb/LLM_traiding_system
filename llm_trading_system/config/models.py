"""Configuration models for LLM Trading System using Pydantic."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ApiConfig(BaseModel):
    """API endpoints and credentials configuration."""

    model_config = ConfigDict(extra="forbid")

    newsapi_key: str | None = None
    newsapi_base_url: str = "https://newsapi.org/v2"

    cryptopanic_api_key: str | None = None
    cryptopanic_base_url: str = "https://cryptopanic.com/api/v1"

    coinmetrics_base_url: str = "https://community-api.coinmetrics.io/v4"
    blockchain_com_base_url: str = "https://api.blockchain.info"

    binance_base_url: str = "https://api.binance.com"
    binance_fapi_url: str = "https://fapi.binance.com"


class LlmConfig(BaseModel):
    """LLM provider and model configuration."""

    model_config = ConfigDict(extra="forbid")

    llm_provider: str = Field(
        default="ollama",
        description="LLM provider: 'ollama', 'openai', or 'router'"
    )
    default_model: str = Field(
        default="llama3.2",
        description="Default model name for the chosen provider"
    )

    ollama_base_url: str = "http://localhost:11434"
    openai_api_base: str | None = None
    openai_api_key: str | None = None

    temperature: float = Field(
        default=0.1,
        ge=0.0,
        le=2.0,
        description="Sampling temperature for LLM"
    )
    timeout_seconds: int = Field(
        default=60,
        ge=1,
        description="Request timeout in seconds"
    )


class MarketConfig(BaseModel):
    """Market data and snapshot configuration."""

    model_config = ConfigDict(extra="forbid")

    base_asset: str = Field(
        default="BTCUSDT",
        description="Primary trading symbol"
    )
    horizon_hours: int = Field(
        default=4,
        ge=1,
        description="Prediction horizon in hours"
    )

    use_news: bool = Field(
        default=True,
        description="Enable news sentiment analysis"
    )
    use_onchain: bool = Field(
        default=True,
        description="Enable on-chain metrics"
    )
    use_funding: bool = Field(
        default=True,
        description="Enable funding rate analysis"
    )


class RiskConfig(BaseModel):
    """Risk management and position sizing parameters."""

    model_config = ConfigDict(extra="forbid")

    base_long_size: float = Field(
        default=0.01,
        ge=0.0,
        le=1.0,
        description="Base position size for long (fraction of capital)"
    )
    base_short_size: float = Field(
        default=0.01,
        ge=0.0,
        le=1.0,
        description="Base position size for short (fraction of capital)"
    )

    k_max: float = Field(
        default=2.0,
        ge=0.0,
        description="Maximum position multiplier"
    )
    edge_gain: float = Field(
        default=2.5,
        ge=0.0,
        description="Edge amplification factor"
    )
    edge_gamma: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Nonlinear edge compression exponent"
    )
    base_k: float = Field(
        default=0.5,
        ge=0.0,
        description="Base multiplier for neutral regime"
    )

    # Stop Loss / Take Profit (Issue #4 fix)
    stop_loss_pct: float = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
        description="Stop loss percentage (0.05 = 5% loss triggers exit)"
    )
    take_profit_pct: float = Field(
        default=0.10,
        ge=0.0,
        le=10.0,
        description="Take profit percentage (0.10 = 10% profit triggers exit)"
    )
    trailing_stop_pct: float = Field(
        default=0.03,
        ge=0.0,
        le=1.0,
        description="Trailing stop percentage (0.03 = 3% from peak)"
    )
    max_position_hold_minutes: int = Field(
        default=1440,  # 24 hours
        ge=0,
        description="Maximum time to hold a position in minutes (0 = unlimited)"
    )
    enable_stop_loss: bool = Field(
        default=True,
        description="Enable automatic stop loss"
    )
    enable_take_profit: bool = Field(
        default=True,
        description="Enable automatic take profit"
    )
    enable_trailing_stop: bool = Field(
        default=False,
        description="Enable trailing stop (follows profit upward)"
    )
    enable_time_exit: bool = Field(
        default=False,
        description="Enable time-based position exit"
    )


class ExchangeConfig(BaseModel):
    """Exchange connection and live trading configuration."""

    model_config = ConfigDict(extra="forbid")

    exchange_type: str = Field(
        default="paper",
        description="Exchange type: 'paper' for simulation, 'binance' for real exchange"
    )

    exchange_name: str = Field(
        default="binance",
        description="Exchange name (binance, etc.)"
    )

    api_key: str | None = None
    api_secret: str | None = None

    use_testnet: bool = Field(
        default=True,
        description="Use testnet instead of mainnet (Binance testnet vs mainnet)"
    )
    live_trading_enabled: bool = Field(
        default=False,
        description="Enable live trading (safety flag)"
    )

    default_symbol: str = Field(
        default="BTCUSDT",
        description="Default symbol for live trading"
    )
    default_timeframe: str = Field(
        default="5m",
        description="Default timeframe for live trading"
    )


class UiDefaultsConfig(BaseModel):
    """UI default values for forms and backtests."""

    model_config = ConfigDict(extra="forbid")

    default_initial_deposit: float = Field(
        default=1000.0,
        ge=0.0,
        description="Default initial deposit for backtests"
    )
    default_backtest_equity: float = Field(
        default=1000.0,
        ge=0.0,
        description="Default equity for backtests"
    )
    default_commission: float = Field(
        default=0.04,
        ge=0.0,
        le=100.0,
        description="Default commission percentage"
    )
    default_slippage: float = Field(
        default=0.0,
        ge=0.0,
        description="Default slippage percentage"
    )


class AppConfig(BaseModel):
    """Root application configuration containing all sub-configs."""

    model_config = ConfigDict(extra="forbid")

    api: ApiConfig = Field(default_factory=ApiConfig)
    llm: LlmConfig = Field(default_factory=LlmConfig)
    market: MarketConfig = Field(default_factory=MarketConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    exchange: ExchangeConfig = Field(default_factory=ExchangeConfig)
    ui: UiDefaultsConfig = Field(default_factory=UiDefaultsConfig)
