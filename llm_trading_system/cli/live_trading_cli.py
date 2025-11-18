"""CLI for live/paper trading with strategies and LLM integration.

This module provides a command-line interface for running live or paper trading
using indicator strategies with optional LLM regime filtering.

Usage:
    llm-trading-live --mode paper --strategy-config my_strategy.json
    llm-trading-live --mode live --strategy-config my_strategy.json --yes-i-know-this-is-real-money
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from llm_trading_system.engine import LiveTradingEngine, PortfolioSimulator
from llm_trading_system.exchange import get_exchange_client_from_env
from llm_trading_system.strategies import (
    IndicatorStrategy,
    IndicatorStrategyConfig,
    LLMRegimeConfig,
    LLMRegimeWrappedStrategy,
)
from llm_trading_system.strategies.base import AccountState

logger = logging.getLogger(__name__)


def setup_logging(level: str = "INFO") -> None:
    """Configure logging for the CLI.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR)
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    # Configure root logger
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Set specific levels for noisy libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)


def load_strategy_config(config_path: Path) -> IndicatorStrategyConfig:
    """Load strategy configuration from JSON file.

    Args:
        config_path: Path to strategy JSON file

    Returns:
        IndicatorStrategyConfig instance

    Raises:
        FileNotFoundError: If config file doesn't exist
        ValueError: If config is invalid
    """
    if not config_path.exists():
        raise FileNotFoundError(f"Strategy config not found: {config_path}")

    import json

    with config_path.open("r", encoding="utf-8") as f:
        config_dict = json.load(f)

    # Convert to IndicatorStrategyConfig
    return IndicatorStrategyConfig.from_dict(config_dict)


def create_llm_client(model: str, provider: str = "ollama"):
    """Create LLM client for regime analysis.

    Args:
        model: Model name (e.g., "llama3.2", "gpt-4")
        provider: Provider name ("ollama" or "openai")

    Returns:
        LLM client instance
    """
    from llm_trading_system.config import load_config

    cfg = load_config()

    if provider == "ollama":
        from llm_trading_system.infra.llm_infra.providers_ollama import OllamaProvider
        from llm_trading_system.infra.llm_infra.client_sync import SyncLLMClient

        base_url = cfg.llm.ollama_base_url
        llm_provider = OllamaProvider(model=model, base_url=base_url)
        return SyncLLMClient(provider=llm_provider)

    elif provider == "openai":
        from llm_trading_system.infra.llm_infra.providers_openai import OpenAIProvider
        from llm_trading_system.infra.llm_infra.client_sync import SyncLLMClient

        api_key = cfg.llm.openai_api_key
        if not api_key:
            raise ValueError(
                "OpenAI API key not configured. "
                "Set it in Settings UI or OPENAI_API_KEY environment variable."
            )

        llm_provider = OpenAIProvider(model=model, api_key=api_key)
        return SyncLLMClient(provider=llm_provider)

    else:
        raise ValueError(f"Unknown provider: {provider}")


def verify_live_mode_safety() -> bool:
    """Verify that live mode is properly configured and safe to use.

    Returns:
        True if safe to proceed

    Raises:
        ValueError: If configuration is unsafe
    """
    from llm_trading_system.config import load_config

    cfg = load_config()

    # Check EXCHANGE_TYPE
    if cfg.exchange.exchange_type != "binance":
        raise ValueError(
            f"exchange_type must be 'binance' for live mode, got '{cfg.exchange.exchange_type}'. "
            f"Configure in Settings UI or set EXCHANGE_TYPE=binance in .env"
        )

    # Check EXCHANGE_LIVE_ENABLED
    if not cfg.exchange.live_trading_enabled:
        raise ValueError(
            "live_trading_enabled must be true for live trading. "
            "Enable in Settings UI or set EXCHANGE_LIVE_ENABLED=true in .env to acknowledge risks."
        )

    # Check API credentials
    if not cfg.exchange.api_key or not cfg.exchange.api_secret:
        raise ValueError(
            "Binance API key and secret must be configured for live trading. "
            "Set them in Settings UI or BINANCE_API_KEY/BINANCE_API_SECRET in .env"
        )

    # Warn about testnet
    if cfg.exchange.use_testnet:
        logger.warning("⚠️  use_testnet=true - Using testnet mode")
        logger.warning("⚠️  This is NOT real trading, just testing")
    else:
        logger.warning("🚨 use_testnet=false - REAL MONEY MODE 🚨")
        logger.warning("🚨 This will execute REAL trades with REAL money 🚨")

    return True


def print_startup_banner(args: argparse.Namespace, config: IndicatorStrategyConfig) -> None:
    """Print startup banner with configuration summary.

    Args:
        args: Command-line arguments
        config: Strategy configuration
    """
    print("\n" + "=" * 70)
    print("🚀 LLM Trading System - Live Trading CLI")
    print("=" * 70)
    print(f"Mode:       {args.mode.upper()}")
    print(f"Symbol:     {args.symbol}")
    print(f"Timeframe:  {args.timeframe}")
    print(f"Strategy:   {args.strategy_config}")
    print(f"LLM:        {'Enabled' if args.llm_enabled else 'Disabled'}")
    if args.llm_enabled:
        print(f"  Model:    {args.llm_model}")
        print(f"  Horizon:  {args.horizon_bars} bars")
    print(f"Equity:     ${args.initial_equity:,.2f}")
    print(f"Base Size:  {config.base_size * 100:.2f}%")
    print("=" * 70 + "\n")


def print_shutdown_summary(engine) -> None:
    """Print summary statistics on shutdown.

    Args:
        engine: LiveTradingEngine instance
    """
    result = engine.result

    print("\n" + "=" * 70)
    print("📊 Trading Session Summary")
    print("=" * 70)

    if result.start_time and result.end_time:
        duration = (result.end_time - result.start_time).total_seconds()
        print(f"Duration:        {duration / 3600:.2f} hours")

    print(f"Bars Processed:  {result.bars_processed}")
    print(f"Orders Executed: {result.orders_executed}")
    print(f"Trades Closed:   {len(result.trades)}")

    if result.equity_curve:
        initial_equity = result.equity_curve[0][1]
        final_equity = result.equity_curve[-1][1]
        pnl = final_equity - initial_equity
        pnl_pct = (pnl / initial_equity) * 100

        print(f"\nInitial Equity:  ${initial_equity:,.2f}")
        print(f"Final Equity:    ${final_equity:,.2f}")
        print(f"P&L:             ${pnl:+,.2f} ({pnl_pct:+.2f}%)")

    if result.errors:
        print(f"\n⚠️  Errors:         {len(result.errors)}")
        for i, error in enumerate(result.errors[:5], 1):
            print(f"  {i}. {error}")
        if len(result.errors) > 5:
            print(f"  ... and {len(result.errors) - 5} more")

    print("=" * 70 + "\n")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        Parsed arguments
    """
    parser = argparse.ArgumentParser(
        description="Live/Paper Trading CLI with LLM Integration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Paper trading with indicator strategy
  llm-trading-live --mode paper --strategy-config examples/night_cat_samurai_strategy.json

  # Paper trading with LLM regime filter
  llm-trading-live --mode paper --strategy-config my_strategy.json --llm-enabled

  # Live trading (REAL MONEY - requires safety flags)
  llm-trading-live --mode live --strategy-config my_strategy.json --yes-i-know-this-is-real-money

Environment Variables:
  EXCHANGE_TYPE              paper or binance (default: paper)
  EXCHANGE_LIVE_ENABLED      true to enable live trading (safety)
  BINANCE_API_KEY            Binance API key (required for live)
  BINANCE_API_SECRET         Binance API secret (required for live)
  BINANCE_TESTNET            true for testnet, false for mainnet
  OLLAMA_BASE_URL            Ollama API URL (default: http://localhost:11434)
  OPENAI_API_KEY             OpenAI API key (for LLM)
        """,
    )

    # Required arguments
    parser.add_argument(
        "--mode",
        choices=["paper", "live"],
        default="paper",
        help="Trading mode: paper (simulation) or live (real money)",
    )

    parser.add_argument(
        "--strategy-config",
        type=Path,
        required=True,
        help="Path to strategy JSON configuration file",
    )

    # Symbol and timeframe
    parser.add_argument(
        "--symbol",
        default=None,
        help="Trading symbol (overrides config, e.g., BTCUSDT)",
    )

    parser.add_argument(
        "--timeframe",
        default="5m",
        help="Bar timeframe: 1m, 5m, 15m, 1h, etc. (default: 5m)",
    )

    # Portfolio settings
    parser.add_argument(
        "--initial-equity",
        type=float,
        default=10000.0,
        help="Initial portfolio equity in USDT (default: 10000)",
    )

    parser.add_argument(
        "--fee-rate",
        type=float,
        default=0.0005,
        help="Trading fee rate (default: 0.0005 = 0.05%%)",
    )

    # LLM settings
    parser.add_argument(
        "--llm-enabled",
        action="store_true",
        help="Enable LLM regime filtering",
    )

    parser.add_argument(
        "--llm-model",
        default="llama3.2",
        help="LLM model name (default: llama3.2)",
    )

    parser.add_argument(
        "--llm-provider",
        choices=["ollama", "openai"],
        default="ollama",
        help="LLM provider (default: ollama)",
    )

    parser.add_argument(
        "--horizon-bars",
        type=int,
        default=48,
        help="LLM refresh interval in bars (default: 48)",
    )

    parser.add_argument(
        "--k-max",
        type=float,
        default=2.0,
        help="Maximum LLM position multiplier (default: 2.0)",
    )

    parser.add_argument(
        "--temperature",
        type=float,
        default=0.1,
        help="LLM temperature (default: 0.1)",
    )

    # Engine settings
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="Exchange poll interval in seconds (default: 1.0)",
    )

    # Safety
    parser.add_argument(
        "--yes-i-know-this-is-real-money",
        action="store_true",
        help="Required flag for live trading (confirms you understand the risks)",
    )

    # Logging
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level (default: INFO)",
    )

    args = parser.parse_args()

    # Validate live mode safety
    if args.mode == "live":
        if not args.yes_i_know_this_is_real_money:
            parser.error(
                "Live trading requires --yes-i-know-this-is-real-money flag. "
                "This confirms you understand you are trading REAL MONEY."
            )

    return args


def main() -> int:
    """Main entry point for live trading CLI.

    Returns:
        Exit code (0 for success, 1 for error)
    """
    try:
        # Parse arguments
        args = parse_args()

        # Setup logging
        setup_logging(args.log_level)

        logger.info("Starting LLM Trading System - Live Trading CLI")

        # Load strategy configuration
        logger.info(f"Loading strategy config from: {args.strategy_config}")
        strategy_config = load_strategy_config(args.strategy_config)

        # Override symbol if provided
        if args.symbol:
            strategy_config.symbol = args.symbol

        # Create indicator strategy
        logger.info(f"Creating IndicatorStrategy for {strategy_config.symbol}")
        indicator_strategy = IndicatorStrategy(
            strategy_config.symbol, strategy_config
        )

        # Wrap with LLM if enabled
        if args.llm_enabled:
            logger.info(f"Creating LLM client: {args.llm_provider}/{args.llm_model}")
            llm_client = create_llm_client(args.llm_model, args.llm_provider)

            # Load AppConfig for risk defaults
            from llm_trading_system.config import load_config
            cfg = load_config()

            # Use CLI args if explicitly different from defaults, otherwise use AppConfig
            # This ensures Settings UI configuration is respected
            k_max_value = args.k_max if args.k_max != 2.0 else cfg.risk.k_max
            temperature_value = args.temperature if args.temperature != 0.1 else cfg.llm.temperature

            regime_config = LLMRegimeConfig(
                horizon_bars=args.horizon_bars,
                base_size=strategy_config.base_size,
                k_max=k_max_value,
                temperature=temperature_value,
                base_asset=strategy_config.symbol.replace("/", ""),
                use_onchain_data=False,  # Disable for live (slow)
                use_news_data=False,  # Disable for live (slow)
            )

            logger.info(
                f"LLM regime config: k_max={k_max_value:.2f}, temperature={temperature_value:.2f} "
                f"(using AppConfig defaults for unspecified parameters)"
            )
            logger.info("Wrapping strategy with LLM regime filter")
            strategy = LLMRegimeWrappedStrategy(
                inner_strategy=indicator_strategy,
                llm_client=llm_client,
                regime_config=regime_config,
            )
        else:
            strategy = indicator_strategy

        # Verify live mode safety
        if args.mode == "live":
            logger.info("Verifying live mode safety...")
            verify_live_mode_safety()
            os.environ["EXCHANGE_TYPE"] = "binance"
        else:
            logger.info("Using paper trading mode")
            os.environ["EXCHANGE_TYPE"] = "paper"

        # Create exchange client
        logger.info(f"Creating exchange client: {os.getenv('EXCHANGE_TYPE')}")
        exchange = get_exchange_client_from_env()

        # Create portfolio
        logger.info(f"Creating portfolio with ${args.initial_equity:,.2f} equity")
        portfolio = PortfolioSimulator(
            symbol=strategy_config.symbol,
            account=AccountState(
                equity=args.initial_equity,
                position_size=0.0,
                entry_price=None,
                symbol=strategy_config.symbol,
            ),
            fee_rate=args.fee_rate,
        )

        # Create live trading engine
        logger.info(
            f"Creating LiveTradingEngine: timeframe={args.timeframe}, "
            f"poll_interval={args.poll_interval}s"
        )
        engine = LiveTradingEngine(
            strategy=strategy,
            exchange=exchange,
            portfolio=portfolio,
            symbol=strategy_config.symbol,
            timeframe=args.timeframe,
            poll_interval_sec=args.poll_interval,
        )

        # Print startup banner
        print_startup_banner(args, strategy_config)

        # Run trading engine
        logger.info("🚀 Starting live trading engine (Ctrl+C to stop)")
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] 🚀 Trading started - Press Ctrl+C to stop\n"
        )

        try:
            result = engine.run_forever()
        except KeyboardInterrupt:
            logger.info("Received interrupt signal, shutting down...")
            print(
                f"\n[{datetime.now().strftime('%H:%M:%S')}] 🛑 Shutting down gracefully..."
            )
            engine.stop()

        # Print summary
        print_shutdown_summary(engine)

        logger.info("Live trading CLI terminated successfully")
        return 0

    except KeyboardInterrupt:
        print("\n\n🛑 Interrupted by user")
        return 130  # Standard exit code for Ctrl+C

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        print(f"\n❌ Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
