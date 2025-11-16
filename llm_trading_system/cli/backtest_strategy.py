#!/usr/bin/env python3
"""CLI for running backtests from JSON strategy configurations."""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from llm_trading_system.engine.backtester import Backtester
from llm_trading_system.engine.data_feed import CSVDataFeed
from llm_trading_system.infra.llm_infra import LLMClientSync, OllamaProvider, RetryPolicy
from llm_trading_system.strategies import create_strategy_from_config
from llm_trading_system.strategies.modes import StrategyMode


def setup_logging(verbose: bool = False) -> None:
    """Configure logging for the CLI."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


def load_config(config_path: Path) -> dict[str, Any]:
    """Load strategy configuration from JSON file.

    Args:
        config_path: Path to JSON config file

    Returns:
        Configuration dictionary

    Raises:
        FileNotFoundError: If config file doesn't exist
        json.JSONDecodeError: If config file is invalid JSON
    """
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def create_llm_client(
    model: str = "llama3.2",
    ollama_url: str = "http://localhost:11434",
) -> LLMClientSync:
    """Create LLM client for strategies that need it.

    Args:
        model: Model name to use
        ollama_url: Ollama server URL

    Returns:
        LLM client instance
    """
    provider = OllamaProvider(model=model, base_url=ollama_url, timeout=120)
    retry_policy = RetryPolicy(max_retries=3, initial_delay=1.0, max_delay=10.0)
    return LLMClientSync(provider=provider, retry_policy=retry_policy)


def compute_metrics(result) -> dict[str, Any]:
    """Compute performance metrics from backtest result.

    Args:
        result: BacktestResult from backtester

    Returns:
        Dictionary of metrics
    """
    # Calculate win rate
    if len(result.trades) > 0:
        winning_trades = sum(1 for t in result.trades if t.pnl and t.pnl > 0)
        win_rate = (winning_trades / len(result.trades)) * 100
    else:
        win_rate = 0.0

    # Calculate average trade P&L
    if len(result.trades) > 0:
        avg_trade_pnl = sum(t.pnl or 0 for t in result.trades) / len(result.trades)
    else:
        avg_trade_pnl = 0.0

    return {
        "total_return_pct": result.total_return * 100,
        "max_drawdown_pct": result.max_drawdown * 100,
        "num_trades": len(result.trades),
        "win_rate_pct": win_rate,
        "avg_trade_pnl": avg_trade_pnl,
        "final_equity": result.final_equity,
        "num_bars": len(result.equity_curve),
    }


def print_results(metrics: dict[str, Any], symbol: str) -> None:
    """Print backtest results in a readable format.

    Args:
        metrics: Dictionary of performance metrics
        symbol: Trading symbol
    """
    print("\n" + "=" * 60)
    print("BACKTEST RESULTS")
    print("=" * 60)
    print(f"Symbol:          {symbol}")
    print(f"Bars:            {metrics['num_bars']}")
    print(f"Trades:          {metrics['num_trades']}")
    print(f"P&L:             {metrics['total_return_pct']:+.2f}%")
    print(f"Max Drawdown:    {metrics['max_drawdown_pct']:.2f}%")
    print(f"Win Rate:        {metrics['win_rate_pct']:.1f}%")
    print(f"Avg Trade P&L:   ${metrics['avg_trade_pnl']:.2f}")
    print(f"Final Equity:    ${metrics['final_equity']:.2f}")
    print("=" * 60)


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Run backtests from JSON strategy configurations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Required arguments
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to JSON strategy configuration file",
    )
    parser.add_argument(
        "--data",
        type=Path,
        required=True,
        help="Path to CSV file with OHLCV data",
    )

    # Optional arguments
    parser.add_argument(
        "--symbol",
        type=str,
        help="Trading symbol (overrides config)",
    )
    parser.add_argument(
        "--initial-equity",
        type=float,
        default=10_000.0,
        help="Initial equity for backtest (default: 10000)",
    )
    parser.add_argument(
        "--fee-rate",
        type=float,
        default=0.001,
        help="Trading fee rate (default: 0.001 = 0.1%%)",
    )
    parser.add_argument(
        "--slippage-bps",
        type=float,
        default=1.0,
        help="Slippage in basis points (default: 1.0)",
    )

    # LLM-related arguments
    parser.add_argument(
        "--use-llm",
        action="store_true",
        help="Enable LLM for combined strategies (requires Ollama)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="llama3.2",
        help="LLM model name (default: llama3.2)",
    )
    parser.add_argument(
        "--ollama-url",
        type=str,
        default="http://localhost:11434",
        help="Ollama server URL (default: http://localhost:11434)",
    )

    # Other options
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    try:
        # Load configuration
        logger.info(f"Loading configuration from {args.config}")
        config = load_config(args.config)

        # Override symbol if provided
        if args.symbol:
            config["symbol"] = args.symbol

        symbol = config.get("symbol", "BTCUSDT")

        # Determine if we need LLM
        mode = config.get("mode", "quant_only")
        strategy_type = config.get("strategy_type", "indicator")

        needs_llm = (
            strategy_type == "combined"
            and mode in ("llm_only", "hybrid")
            and args.use_llm
        )

        # Create LLM client if needed
        llm_client = None
        if needs_llm:
            logger.info(f"Creating LLM client with model: {args.model}")
            try:
                llm_client = create_llm_client(
                    model=args.model,
                    ollama_url=args.ollama_url,
                )
            except Exception as e:
                logger.error(f"Failed to create LLM client: {e}")
                logger.warning("Falling back to QUANT_ONLY mode")
                config["mode"] = "quant_only"
        elif mode in ("llm_only", "hybrid") and not args.use_llm:
            logger.warning(
                f"Strategy requires LLM (mode={mode}) but --use-llm not set. "
                "Forcing QUANT_ONLY mode"
            )
            config["mode"] = "quant_only"

        # Create strategy
        logger.info(f"Creating strategy: type={strategy_type}, mode={config.get('mode')}")
        strategy = create_strategy_from_config(config, llm_client=llm_client)

        # Load data
        logger.info(f"Loading data from {args.data}")
        if not args.data.exists():
            raise FileNotFoundError(f"Data file not found: {args.data}")

        data_feed = CSVDataFeed(path=args.data, symbol=symbol)

        # Create backtester
        logger.info("Running backtest...")
        backtester = Backtester(
            strategy=strategy,
            data_feed=data_feed,
            initial_equity=args.initial_equity,
            fee_rate=args.fee_rate,
            slippage_bps=args.slippage_bps,
            symbol=symbol,
        )

        # Run backtest
        result = backtester.run()

        # Compute and print metrics
        metrics = compute_metrics(result)
        print_results(metrics, symbol)

        # Print trade details if verbose
        if args.verbose and result.trades:
            print("\nTrade Details:")
            print("-" * 60)
            for i, trade in enumerate(result.trades, 1):
                print(
                    f"Trade {i}: {trade.side.upper()} | "
                    f"Entry: ${trade.entry_price:.2f} | "
                    f"Exit: ${trade.exit_price or 0:.2f} | "
                    f"P&L: ${trade.pnl or 0:.2f}"
                )

        # Exit with appropriate code
        sys.exit(0 if metrics["total_return_pct"] >= 0 else 1)

    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in config file: {e}")
        sys.exit(1)
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
