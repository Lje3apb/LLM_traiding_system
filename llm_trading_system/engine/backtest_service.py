"""Backtest service layer for running backtests from configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from llm_trading_system.engine.backtester import Backtester
from llm_trading_system.engine.data_feed import CSVDataFeed
from llm_trading_system.strategies import create_strategy_from_config


def run_backtest_from_config_dict(
    config: dict[str, Any],
    data_path: str,
    use_llm: bool = False,
    llm_model: str | None = None,
    llm_url: str | None = None,
    initial_equity: float = 10_000.0,
    fee_rate: float = 0.001,
    slippage_bps: float = 1.0,
) -> dict[str, Any]:
    """Run a backtest from a configuration dictionary.

    Args:
        config: Strategy configuration dictionary
        data_path: Path to CSV file with OHLCV data
        use_llm: Whether to use LLM for strategies that support it
        llm_model: LLM model name (default: llama3.2)
        llm_url: Ollama server URL (default: http://localhost:11434)
        initial_equity: Starting capital
        fee_rate: Trading fee rate
        slippage_bps: Slippage in basis points

    Returns:
        Dictionary with backtest results:
            - symbol: str
            - bars: int
            - trades: int
            - pnl_abs: float
            - pnl_pct: float
            - max_drawdown: float
            - win_rate: float
            - final_equity: float
            - equity_curve: list[dict] (optional)

    Raises:
        FileNotFoundError: If data file doesn't exist
        ValueError: If configuration is invalid
    """
    # Set defaults from AppConfig (provides consistency with Settings UI)
    if llm_model is None or llm_url is None:
        from llm_trading_system.config import load_config

        cfg = load_config()
        if llm_model is None:
            llm_model = cfg.llm.default_model
        if llm_url is None:
            llm_url = cfg.llm.ollama_base_url

    # Get symbol from config
    symbol = config.get("symbol", "BTCUSDT")

    # Determine if we need LLM
    mode = config.get("mode", "quant_only")
    strategy_type = config.get("strategy_type", "indicator")
    needs_llm = (
        strategy_type == "combined" and mode in ("llm_only", "hybrid") and use_llm
    )

    # Create LLM client if needed
    llm_client = None
    if needs_llm:
        try:
            from llm_trading_system.infra.llm_infra import (
                LLMClientSync,
                OllamaProvider,
                RetryPolicy,
            )

            provider = OllamaProvider(
                model=llm_model, base_url=llm_url, timeout=120
            )
            retry_policy = RetryPolicy(
                max_retries=3, initial_delay=1.0, max_delay=10.0
            )
            llm_client = LLMClientSync(provider=provider, retry_policy=retry_policy)
        except Exception as e:
            raise ValueError(f"Failed to create LLM client: {e}") from e
    elif mode in ("llm_only", "hybrid") and not use_llm:
        # Force QUANT_ONLY if LLM required but not available
        config = config.copy()
        config["mode"] = "quant_only"

    # Create strategy
    strategy = create_strategy_from_config(config, llm_client=llm_client)

    # Load data
    data_path_obj = Path(data_path)
    if not data_path_obj.exists():
        raise FileNotFoundError(f"Data file not found: {data_path}")

    data_feed = CSVDataFeed(path=data_path_obj, symbol=symbol)

    # Create backtester
    backtester = Backtester(
        strategy=strategy,
        data_feed=data_feed,
        initial_equity=initial_equity,
        fee_rate=fee_rate,
        slippage_bps=slippage_bps,
        symbol=symbol,
    )

    # Run backtest
    result = backtester.run()

    # Compute metrics
    if len(result.trades) > 0:
        winning_trades = sum(1 for t in result.trades if t.pnl and t.pnl > 0)
        win_rate = (winning_trades / len(result.trades)) * 100
        avg_trade_pnl = sum(t.pnl or 0 for t in result.trades) / len(result.trades)
    else:
        win_rate = 0.0
        avg_trade_pnl = 0.0

    pnl_abs = result.final_equity - initial_equity

    # Build summary
    summary = {
        "symbol": symbol,
        "bars": len(result.equity_curve),
        "trades": len(result.trades),
        "pnl_abs": pnl_abs,
        "pnl_pct": result.total_return * 100,
        "max_drawdown": result.max_drawdown * 100,
        "win_rate": win_rate,
        "avg_trade_pnl": avg_trade_pnl,
        "final_equity": result.final_equity,
        "initial_equity": initial_equity,
        "trades_list": result.trades,  # Include full trades list for caching
    }

    # Optionally include equity curve
    summary["equity_curve"] = [
        {"timestamp": ts.isoformat(), "equity": eq}
        for ts, eq in result.equity_curve
    ]

    return summary


__all__ = ["run_backtest_from_config_dict"]
