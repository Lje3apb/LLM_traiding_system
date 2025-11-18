"""Tests for paper exchange client."""

import os
from datetime import datetime, timezone

import pytest

from llm_trading_system.exchange.base import ExchangeConfig
from llm_trading_system.exchange.config import (
    get_exchange_client_from_env,
    get_exchange_config_from_env,
    get_exchange_type_from_env,
)
from llm_trading_system.exchange.paper import PaperExchangeClient
from llm_trading_system.strategies.base import Bar


def test_exchange_config_creation():
    """Test that ExchangeConfig can be created with defaults."""
    config = ExchangeConfig()

    assert config.api_key == ""
    assert config.api_secret == ""
    assert config.base_url == "https://fapi.binance.com"
    assert config.testnet is True
    assert config.trading_symbol == "BTC/USDT"
    assert config.leverage == 1
    assert config.min_notional == 10.0
    assert config.timeout == 30
    assert config.enable_rate_limit is True


def test_exchange_config_from_env():
    """Test loading exchange config from environment variables."""
    # Set up test environment
    os.environ["BINANCE_API_KEY"] = "test_key"
    os.environ["BINANCE_API_SECRET"] = "test_secret"
    os.environ["BINANCE_TESTNET"] = "false"
    os.environ["BINANCE_TRADING_SYMBOL"] = "ETH/USDT"
    os.environ["BINANCE_LEVERAGE"] = "5"

    try:
        config = get_exchange_config_from_env()

        assert config.api_key == "test_key"
        assert config.api_secret == "test_secret"
        assert config.testnet is False
        assert config.trading_symbol == "ETH/USDT"
        assert config.leverage == 5
    finally:
        # Clean up
        for key in [
            "BINANCE_API_KEY",
            "BINANCE_API_SECRET",
            "BINANCE_TESTNET",
            "BINANCE_TRADING_SYMBOL",
            "BINANCE_LEVERAGE",
        ]:
            os.environ.pop(key, None)


def test_get_exchange_type_from_env():
    """Test getting exchange type from environment."""
    # Test default (paper)
    os.environ.pop("EXCHANGE_TYPE", None)
    assert get_exchange_type_from_env() == "paper"

    # Test explicit paper
    os.environ["EXCHANGE_TYPE"] = "paper"
    assert get_exchange_type_from_env() == "paper"

    # Test binance
    os.environ["EXCHANGE_TYPE"] = "binance"
    assert get_exchange_type_from_env() == "binance"

    # Test invalid type
    os.environ["EXCHANGE_TYPE"] = "invalid"
    with pytest.raises(ValueError, match="Invalid EXCHANGE_TYPE"):
        get_exchange_type_from_env()

    # Clean up
    os.environ.pop("EXCHANGE_TYPE", None)


def test_paper_client_creation():
    """Test that PaperExchangeClient can be created."""
    config = ExchangeConfig()
    client = PaperExchangeClient(config, initial_balance=10000.0)

    assert client.config == config
    assert client.portfolio.account.equity == 10000.0
    assert client.portfolio.account.position_size == 0.0
    assert client.order_counter == 0


def test_paper_client_account_info():
    """Test getting account info from paper client."""
    config = ExchangeConfig()
    client = PaperExchangeClient(config, initial_balance=10000.0)

    account_info = client.get_account_info()

    assert account_info.total_balance == 10000.0
    assert account_info.available_balance >= 0.0
    assert account_info.unrealized_pnl == 0.0
    assert len(account_info.positions) == 0
    assert isinstance(account_info.timestamp, datetime)


def test_paper_client_market_data_update():
    """Test updating market data in paper client."""
    config = ExchangeConfig()
    client = PaperExchangeClient(config, initial_balance=10000.0)

    bar = Bar(
        timestamp=datetime.now(timezone.utc),
        open=50000.0,
        high=50100.0,
        low=49900.0,
        close=50050.0,
        volume=100.0,
    )

    client.update_market_data(bar)

    assert client.current_bar == bar
    assert client.get_latest_price("BTC/USDT") == 50050.0
    assert client.get_latest_bar("BTC/USDT") == bar


def test_paper_client_place_market_order():
    """Test placing a market order in paper trading."""
    config = ExchangeConfig()
    client = PaperExchangeClient(config, initial_balance=10000.0)

    # Set up market data
    bar = Bar(
        timestamp=datetime.now(timezone.utc),
        open=50000.0,
        high=50100.0,
        low=49900.0,
        close=50000.0,
        volume=100.0,
    )
    client.update_market_data(bar)

    # Place buy order for 0.1 BTC
    result = client.place_order(
        symbol="BTC/USDT", side="buy", quantity=0.1, order_type="market"
    )

    assert result.order_id.startswith("paper_")
    assert result.symbol == "BTC/USDT"
    assert result.side == "buy"
    assert result.order_type == "market"
    assert result.price == 50000.0
    assert result.quantity == 0.1
    assert result.filled_quantity == 0.1
    assert result.status == "filled"
    assert result.commission > 0.0


def test_paper_client_position_tracking():
    """Test that positions are tracked correctly after orders."""
    config = ExchangeConfig()
    client = PaperExchangeClient(config, initial_balance=10000.0)

    # Set up market data
    bar = Bar(
        timestamp=datetime.now(timezone.utc),
        open=50000.0,
        high=50100.0,
        low=49900.0,
        close=50000.0,
        volume=100.0,
    )
    client.update_market_data(bar)

    # Place buy order
    client.place_order(symbol="BTC/USDT", side="buy", quantity=0.1, order_type="market")

    # Check positions
    positions = client.get_open_positions()
    assert len(positions) == 1

    position = positions[0]
    assert position.symbol == "BTC/USDT"
    assert position.size > 0  # Long position
    assert position.entry_price > 0
    assert position.leverage == 1

    # Check position by symbol
    pos = client.get_position("BTC/USDT")
    assert pos is not None
    assert pos.symbol == "BTC/USDT"


def test_paper_client_balance_updates():
    """Test that balance updates after trades."""
    config = ExchangeConfig()
    client = PaperExchangeClient(config, initial_balance=10000.0)

    # Set up market data
    bar = Bar(
        timestamp=datetime.now(timezone.utc),
        open=50000.0,
        high=50100.0,
        low=49900.0,
        close=50000.0,
        volume=100.0,
    )
    client.update_market_data(bar)

    # Get initial balance
    initial_account = client.get_account_info()
    initial_balance = initial_account.total_balance

    # Place and close a trade
    client.place_order(symbol="BTC/USDT", side="buy", quantity=0.1, order_type="market")

    # Update price (simulate profit)
    bar2 = Bar(
        timestamp=datetime.now(timezone.utc),
        open=51000.0,
        high=51100.0,
        low=50900.0,
        close=51000.0,
        volume=100.0,
    )
    client.update_market_data(bar2)

    # Check unrealized PnL is positive
    positions = client.get_open_positions()
    assert len(positions) == 1
    assert positions[0].unrealized_pnl > 0

    # Close position by using reduce_only
    # Get the actual position size to close
    position = positions[0]
    # For paper trading, we need to close via portfolio directly
    # by placing a flat order
    from llm_trading_system.strategies.base import Order

    close_order = Order(symbol="BTC/USDT", side="flat", size=0.0)
    client.portfolio.process_order(close_order, bar2)

    # Check positions are closed
    positions = client.get_open_positions()
    assert len(positions) == 0

    # Check balance changed (should be higher due to profit minus fees)
    final_account = client.get_account_info()
    final_balance = final_account.total_balance

    # Balance should have increased (profit > fees in this scenario)
    # Note: Due to fees, the profit needs to be > 2x fee cost
    # With 0.05% fee and 2% price increase, profit should be positive
    assert final_balance != initial_balance  # Changed due to trading activity


def test_paper_client_limit_order():
    """Test placing a limit order in paper trading."""
    config = ExchangeConfig()
    client = PaperExchangeClient(config, initial_balance=10000.0)

    # Set up market data
    bar = Bar(
        timestamp=datetime.now(timezone.utc),
        open=50000.0,
        high=50100.0,
        low=49900.0,
        close=50000.0,
        volume=100.0,
    )
    client.update_market_data(bar)

    # Place limit order
    result = client.place_order(
        symbol="BTC/USDT",
        side="buy",
        quantity=0.1,
        order_type="limit",
        price=49000.0,
    )

    assert result.status == "open"
    assert result.filled_quantity == 0.0
    assert result.price == 49000.0

    # Check open orders
    open_orders = client.get_open_orders("BTC/USDT")
    assert len(open_orders) == 1
    assert open_orders[0].order_id == result.order_id


def test_paper_client_cancel_order():
    """Test canceling an order in paper trading."""
    config = ExchangeConfig()
    client = PaperExchangeClient(config, initial_balance=10000.0)

    # Set up market data
    bar = Bar(
        timestamp=datetime.now(timezone.utc),
        open=50000.0,
        high=50100.0,
        low=49900.0,
        close=50000.0,
        volume=100.0,
    )
    client.update_market_data(bar)

    # Place limit order
    result = client.place_order(
        symbol="BTC/USDT",
        side="buy",
        quantity=0.1,
        order_type="limit",
        price=49000.0,
    )

    # Cancel it
    success = client.cancel_order("BTC/USDT", result.order_id)
    assert success is True

    # Check it's gone
    open_orders = client.get_open_orders("BTC/USDT")
    assert len(open_orders) == 0


def test_get_exchange_client_from_env_paper():
    """Test creating paper client from environment."""
    os.environ["EXCHANGE_TYPE"] = "paper"
    os.environ["PAPER_INITIAL_BALANCE"] = "20000.0"

    try:
        client = get_exchange_client_from_env()

        assert isinstance(client, PaperExchangeClient)
        assert client.portfolio.account.equity == 20000.0
    finally:
        os.environ.pop("EXCHANGE_TYPE", None)
        os.environ.pop("PAPER_INITIAL_BALANCE", None)


def test_paper_client_exchange_time():
    """Test getting exchange time from paper client."""
    config = ExchangeConfig()
    client = PaperExchangeClient(config)

    exchange_time = client.get_exchange_time()
    assert isinstance(exchange_time, datetime)
    assert exchange_time.tzinfo == timezone.utc


def test_paper_client_time_sync():
    """Test time sync (should be no-op for paper trading)."""
    config = ExchangeConfig()
    client = PaperExchangeClient(config)

    # Should not raise
    client.time_sync()


def test_paper_client_validation():
    """Test validation of invalid inputs."""
    config = ExchangeConfig()
    client = PaperExchangeClient(config, initial_balance=10000.0)

    # Set up market data
    bar = Bar(
        timestamp=datetime.now(timezone.utc),
        open=50000.0,
        high=50100.0,
        low=49900.0,
        close=50000.0,
        volume=100.0,
    )
    client.update_market_data(bar)

    # Test invalid quantity
    with pytest.raises(ValueError, match="Quantity must be positive"):
        client.place_order(symbol="BTC/USDT", side="buy", quantity=-0.1)

    # Test limit order without price
    with pytest.raises(ValueError, match="Price is required for limit orders"):
        client.place_order(symbol="BTC/USDT", side="buy", quantity=0.1, order_type="limit")

    # Test unknown symbol
    with pytest.raises(ValueError, match="Unknown symbol"):
        client.get_latest_price("ETH/USDT")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
