"""Configuration models for LLM Trading System using Pydantic."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ApiConfig(BaseModel):
    """API endpoints and credentials configuration."""

    newsapi_key: str | None = None
    newsapi_base_url: str = "https://newsapi.org/v2"

    cryptopanic_api_key: str | None = None
    cryptopanic_base_url: str = "https://cryptopanic.com/api/v1"

    coinmetrics_base_url: str = "https://community-api.coinmetrics.io/v4"
    blockchain_com_base_url: str = "https://api.blockchain.info"

    binance_base_url: str = "https://api.binance.com"
    binance_fapi_url: str = "https://fapi.binance.com"

    class Config:
        """Pydantic model configuration."""
        extra = "forbid"


class LlmConfig(BaseModel):
    """LLM provider and model configuration."""

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

    class Config:
        """Pydantic model configuration."""
        extra = "forbid"


class MarketConfig(BaseModel):
    """Market data and snapshot configuration."""

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

    class Config:
        """Pydantic model configuration."""
        extra = "forbid"


class RiskConfig(BaseModel):
    """Risk management and position sizing parameters."""

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

    class Config:
        """Pydantic model configuration."""
        extra = "forbid"


class ExchangeConfig(BaseModel):
    """Exchange connection and live trading configuration."""

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

    class Config:
        """Pydantic model configuration."""
        extra = "forbid"


class UiDefaultsConfig(BaseModel):
    """UI default values for forms and backtests."""

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

    class Config:
        """Pydantic model configuration."""
        extra = "forbid"


class AppConfig(BaseModel):
    """Root application configuration containing all sub-configs."""

    api: ApiConfig = Field(default_factory=ApiConfig)
    llm: LlmConfig = Field(default_factory=LlmConfig)
    market: MarketConfig = Field(default_factory=MarketConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    exchange: ExchangeConfig = Field(default_factory=ExchangeConfig)
    ui: UiDefaultsConfig = Field(default_factory=UiDefaultsConfig)

    class Config:
        """Pydantic model configuration."""
        extra = "forbid"
