"""Tests for CSV chunked reading optimization."""

import tempfile
from pathlib import Path

import pandas as pd
import pytest

from llm_trading_system.data.data_manager import DataManager


@pytest.fixture
def temp_csv_file():
    """Create a temporary CSV file for testing."""
    # Create a sample OHLCV dataset
    data = {
        "timestamp": pd.date_range("2024-01-01", periods=10000, freq="1min").strftime("%Y-%m-%d %H:%M:%S"),
        "open": [100.0 + i * 0.1 for i in range(10000)],
        "high": [100.5 + i * 0.1 for i in range(10000)],
        "low": [99.5 + i * 0.1 for i in range(10000)],
        "close": [100.2 + i * 0.1 for i in range(10000)],
        "volume": [1000.0 + i * 10 for i in range(10000)],
    }
    df = pd.DataFrame(data)

    # Save to temporary file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        df.to_csv(f.name, index=False)
        temp_path = Path(f.name)

    yield temp_path

    # Cleanup
    temp_path.unlink(missing_ok=True)


def test_load_csv_without_chunking(temp_csv_file):
    """Test loading CSV without chunking (backward compatibility)."""
    dm = DataManager()
    df = dm.load_from_csv(temp_csv_file)

    assert len(df) == 10000
    assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
    assert df["open"].iloc[0] == 100.0
    assert df["close"].iloc[-1] == pytest.approx(100.2 + 9999 * 0.1, rel=1e-6)


def test_load_csv_with_chunking(temp_csv_file):
    """Test loading CSV with chunking."""
    dm = DataManager()
    df = dm.load_from_csv(temp_csv_file, chunksize=1000)

    assert len(df) == 10000
    assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
    assert df["open"].iloc[0] == 100.0
    assert df["close"].iloc[-1] == pytest.approx(100.2 + 9999 * 0.1, rel=1e-6)


def test_chunked_equals_non_chunked(temp_csv_file):
    """Verify chunked and non-chunked reading produce identical results."""
    dm = DataManager()

    df_normal = dm.load_from_csv(temp_csv_file)
    df_chunked = dm.load_from_csv(temp_csv_file, chunksize=1000)

    # Should have same length
    assert len(df_normal) == len(df_chunked)

    # Should have same columns
    assert list(df_normal.columns) == list(df_chunked.columns)

    # Compare data (convert to ensure same dtypes)
    pd.testing.assert_frame_equal(
        df_normal.reset_index(drop=True),
        df_chunked.reset_index(drop=True),
        check_dtype=False  # Allow minor dtype differences
    )


def test_check_data_coverage_optimized(temp_csv_file):
    """Test optimized data coverage check (should not load entire file)."""
    dm = DataManager()

    # This should work without loading the entire file
    # The test file has data from 2024-01-01 for 10000 minutes (~7 days)
    covers_range = dm.check_data_coverage(temp_csv_file, "2024-01-02", "2024-01-05")

    assert covers_range is True


def test_check_data_coverage_out_of_range(temp_csv_file):
    """Test data coverage check with out-of-range dates."""
    dm = DataManager()

    # File only has data from 2024-01-01 onwards
    covers_range = dm.check_data_coverage(temp_csv_file, "2023-12-01", "2023-12-31")

    assert covers_range is False


def test_chunked_reading_with_small_chunksize(temp_csv_file):
    """Test chunked reading with very small chunk size."""
    dm = DataManager()

    # Use very small chunk size to test multiple chunks
    df = dm.load_from_csv(temp_csv_file, chunksize=100)

    assert len(df) == 10000
    assert df["open"].iloc[0] == 100.0


def test_chunked_reading_with_large_chunksize(temp_csv_file):
    """Test chunked reading with chunk size larger than file."""
    dm = DataManager()

    # Chunk size larger than file
    df = dm.load_from_csv(temp_csv_file, chunksize=100000)

    assert len(df) == 10000
    assert df["open"].iloc[0] == 100.0
