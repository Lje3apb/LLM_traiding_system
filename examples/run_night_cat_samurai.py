"""Example: Running the Night Cat Samurai strategy backtest.

This script demonstrates how to:
1. Load the strategy configuration from JSON
2. Create a data feed
3. Run a backtest
4. Display results
"""

import json
from pathlib import Path

from llm_trading_system.engine.backtester import Backtester
from llm_trading_system.engine.data_feed import CSVDataFeed
from llm_trading_system.strategies.factory import create_strategy_from_config


def main():
    # Load strategy configuration
    config_path = Path(__file__).parent / "night_cat_samurai_strategy.json"
    with open(config_path, "r") as f:
        config = json.load(f)

    print(f"Loading strategy: {config['name']}")
    print(f"Symbol: {config['symbol']}")
    print(f"Pyramiding: {config['pyramiding']}")
    print(f"Martingale multiplier: {config['martingale_mult']}")
    print()

    # Create strategy
    strategy = create_strategy_from_config(config, llm_client=None)

    # Create data feed (adjust path to your data file)
    # Expected format: CSV with columns: timestamp,open,high,low,close,volume
    data_path = Path("data/ETHUSDT_5m.csv")

    if not data_path.exists():
        print(f"Error: Data file not found at {data_path}")
        print("Please provide a CSV file with OHLCV data.")
        return

    data_feed = CSVDataFeed(path=data_path, symbol=config["symbol"])

    # Create and run backtester
    # Note: initial_capital from Pine Script was 50, but that's unusually low
    # Adjust to realistic values (e.g., 10000)
    backtester = Backtester(
        strategy=strategy,
        data_feed=data_feed,
        initial_equity=10000.0,  # Starting capital
        fee_rate=0.0004,         # 0.04% commission
        slippage_bps=1.0,        # 1 basis point slippage
        symbol=config["symbol"],
    )

    print("Running backtest...")
    result = backtester.run()

    # Display results
    print("\n" + "=" * 60)
    print("BACKTEST RESULTS")
    print("=" * 60)
    print(f"Final equity:     ${result.final_equity:,.2f}")
    print(f"Total return:     {result.total_return:.2%}")
    print(f"Max drawdown:     {result.max_drawdown:.2%}")
    print(f"Number of trades: {len(result.trades)}")
    print()

    # Show first few trades
    if result.trades:
        print("First 5 trades:")
        print("-" * 60)
        for i, trade in enumerate(result.trades[:5], 1):
            pnl_str = f"${trade.pnl:,.2f}" if trade.pnl else "N/A"
            print(f"{i}. {trade.side.upper():5} | Entry: ${trade.entry_price:,.2f} | "
                  f"Exit: ${trade.exit_price:,.2f} | PnL: {pnl_str}")

    # Show last few trades
    if len(result.trades) > 5:
        print()
        print("Last 5 trades:")
        print("-" * 60)
        for i, trade in enumerate(result.trades[-5:], len(result.trades) - 4):
            pnl_str = f"${trade.pnl:,.2f}" if trade.pnl else "N/A"
            print(f"{i}. {trade.side.upper():5} | Entry: ${trade.entry_price:,.2f} | "
                  f"Exit: ${trade.exit_price:,.2f} | PnL: {pnl_str}")

    print("=" * 60)


if __name__ == "__main__":
    main()
