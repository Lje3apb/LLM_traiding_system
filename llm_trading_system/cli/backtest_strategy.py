#!/usr/bin/env python3
"""CLI for running backtests from JSON strategy configurations."""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from llm_trading_system.engine.backtest_service import run_backtest_from_config_dict


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


def print_results(summary: dict[str, Any]) -> None:
    """Print backtest results in a readable format.

    Args:
        summary: Dictionary of backtest results from service
    """
    print("\n" + "=" * 60)
    print("BACKTEST RESULTS")
    print("=" * 60)
    print(f"Symbol:          {summary['symbol']}")
    print(f"Bars:            {summary['bars']}")
    print(f"Trades:          {summary['trades']}")
    print(f"P&L:             {summary['pnl_pct']:+.2f}%")
    print(f"Max Drawdown:    {summary['max_drawdown']:.2f}%")
    print(f"Win Rate:        {summary['win_rate']:.1f}%")
    print(f"Avg Trade P&L:   ${summary['avg_trade_pnl']:.2f}")
    print(f"Final Equity:    ${summary['final_equity']:.2f}")
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

        # Run backtest using service layer
        logger.info("Running backtest...")
        summary = run_backtest_from_config_dict(
            config=config,
            data_path=str(args.data),
            use_llm=args.use_llm,
            llm_model=args.model,
            llm_url=args.ollama_url,
            initial_equity=args.initial_equity,
            fee_rate=args.fee_rate,
            slippage_bps=args.slippage_bps,
        )

        # Print results
        print_results(summary)

        # Exit with appropriate code
        sys.exit(0 if summary["pnl_pct"] >= 0 else 1)

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
