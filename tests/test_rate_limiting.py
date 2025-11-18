"""Tests for Binance API rate limiting."""

import time
from datetime import datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from llm_trading_system.data.binance_loader import BinanceArchiveLoader, fetch_klines_archive


@pytest.fixture
def mock_download_day():
    """Mock the _download_day method to avoid real API calls."""
    sample_data = pd.DataFrame({
        "open_time": pd.date_range("2024-01-01", periods=24, freq="1h"),
        "open": [100.0] * 24,
        "high": [101.0] * 24,
        "low": [99.0] * 24,
        "close": [100.5] * 24,
        "volume": [1000.0] * 24,
        "close_time": pd.date_range("2024-01-01 01:00", periods=24, freq="1h"),
        "quote_volume": [100000.0] * 24,
        "trades": [100] * 24,
        "taker_buy_base": [500.0] * 24,
        "taker_buy_quote": [50000.0] * 24,
    })
    return sample_data


def test_rate_limit_default_value():
    """Test that default rate limit is set correctly."""
    loader = BinanceArchiveLoader("BTCUSDT", "1h")
    assert loader.rate_limit_delay == 0.1


def test_rate_limit_custom_value():
    """Test that custom rate limit is set correctly."""
    loader = BinanceArchiveLoader("BTCUSDT", "1h", rate_limit_delay=0.5)
    assert loader.rate_limit_delay == 0.5


def test_rate_limit_zero():
    """Test that rate limiting can be disabled."""
    loader = BinanceArchiveLoader("BTCUSDT", "1h", rate_limit_delay=0.0)
    assert loader.rate_limit_delay == 0.0


@patch.object(BinanceArchiveLoader, '_download_day')
def test_rate_limiting_applies_delay(mock_download, mock_download_day):
    """Test that rate limiting actually adds delays between requests."""
    # Setup mock to return sample data
    mock_download.return_value = mock_download_day

    # Create loader with 0.2s rate limit
    loader = BinanceArchiveLoader("BTCUSDT", "1h", rate_limit_delay=0.2)

    # Download 3 days (should have 2 delays = 0.4s minimum)
    start_time = time.time()
    df = loader.download_range("2024-01-01", "2024-01-03")
    elapsed = time.time() - start_time

    # Should have at least 2 * 0.2 = 0.4 seconds of delays
    assert elapsed >= 0.4, f"Expected at least 0.4s with rate limiting, got {elapsed:.3f}s"

    # Should call _download_day 3 times (once per day)
    assert mock_download.call_count == 3


@patch.object(BinanceArchiveLoader, '_download_day')
def test_no_rate_limiting_when_disabled(mock_download, mock_download_day):
    """Test that no delay is added when rate limiting is disabled."""
    # Setup mock to return sample data
    mock_download.return_value = mock_download_day

    # Create loader with rate limiting disabled
    loader = BinanceArchiveLoader("BTCUSDT", "1h", rate_limit_delay=0.0)

    # Download 3 days
    start_time = time.time()
    df = loader.download_range("2024-01-01", "2024-01-03")
    elapsed = time.time() - start_time

    # Should complete very quickly (< 0.1s) without rate limiting
    assert elapsed < 0.1, f"Expected fast execution without rate limiting, got {elapsed:.3f}s"

    # Should still call _download_day 3 times
    assert mock_download.call_count == 3


@patch.object(BinanceArchiveLoader, '_download_day')
def test_rate_limiting_with_failures(mock_download):
    """Test that rate limiting is applied even when downloads fail."""
    # Setup mock to fail on some days
    def side_effect(date):
        if date.day == 2:
            raise Exception("Network error")
        return pd.DataFrame({
            "open_time": pd.date_range(date, periods=24, freq="1h"),
            "open": [100.0] * 24,
            "high": [101.0] * 24,
            "low": [99.0] * 24,
            "close": [100.5] * 24,
            "volume": [1000.0] * 24,
            "close_time": pd.date_range(date, periods=24, freq="1h"),
            "quote_volume": [100000.0] * 24,
            "trades": [100] * 24,
            "taker_buy_base": [500.0] * 24,
            "taker_buy_quote": [50000.0] * 24,
        })

    mock_download.side_effect = side_effect

    # Create loader with 0.2s rate limit
    loader = BinanceArchiveLoader("BTCUSDT", "1h", rate_limit_delay=0.2)

    # Download 3 days (one will fail)
    start_time = time.time()
    df = loader.download_range("2024-01-01", "2024-01-03")
    elapsed = time.time() - start_time

    # Should still have delays even with failure
    # 3 days = 2 successful delays + 1 failed delay = at least 0.6s
    assert elapsed >= 0.4, f"Expected delays even with failures, got {elapsed:.3f}s"

    # Should have data from 2 days
    assert len(df) > 0


def test_fetch_klines_archive_rate_limit_parameter():
    """Test that fetch_klines_archive passes rate_limit_delay parameter."""
    with patch.object(BinanceArchiveLoader, 'download_range') as mock_download:
        mock_download.return_value = pd.DataFrame({
            "open_time": pd.date_range("2024-01-01", periods=24, freq="1h"),
            "open": [100.0] * 24,
            "high": [101.0] * 24,
            "low": [99.0] * 24,
            "close": [100.5] * 24,
            "volume": [1000.0] * 24,
        })

        # Call with custom rate limit
        df = fetch_klines_archive("BTCUSDT", "1h", "2024-01-01", "2024-01-03", rate_limit_delay=0.5)

        # Should have called download_range
        mock_download.assert_called_once()


def test_rate_limiting_with_single_day():
    """Test that no delay is added when downloading single day."""
    with patch.object(BinanceArchiveLoader, '_download_day') as mock_download:
        mock_download.return_value = pd.DataFrame({
            "open_time": pd.date_range("2024-01-01", periods=24, freq="1h"),
            "open": [100.0] * 24,
            "high": [101.0] * 24,
            "low": [99.0] * 24,
            "close": [100.5] * 24,
            "volume": [1000.0] * 24,
            "close_time": pd.date_range("2024-01-01", periods=24, freq="1h"),
            "quote_volume": [100000.0] * 24,
            "trades": [100] * 24,
            "taker_buy_base": [500.0] * 24,
            "taker_buy_quote": [50000.0] * 24,
        })

        loader = BinanceArchiveLoader("BTCUSDT", "1h", rate_limit_delay=0.5)

        # Download single day
        start_time = time.time()
        df = loader.download_range("2024-01-01", "2024-01-01")
        elapsed = time.time() - start_time

        # Should be fast (no delays needed for single day)
        assert elapsed < 0.1, f"Single day download should be fast, got {elapsed:.3f}s"
