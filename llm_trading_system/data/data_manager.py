"""Data management and caching for OHLCV data."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

from llm_trading_system.data.binance_loader import fetch_klines_archive

logger = logging.getLogger(__name__)


class DataManager:
    """Manager for OHLCV data with caching support."""

    def __init__(self, data_dir: str | Path = "data") -> None:
        """Initialize data manager.

        Args:
            data_dir: Directory for storing CSV files
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)

    def _generate_filename(self, symbol: str, interval: str, start_date: str, end_date: str) -> str:
        """Generate filename for data file.

        Args:
            symbol: Trading pair
            interval: Candle interval
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)

        Returns:
            Filename without path
        """
        return f"{symbol}_{interval}_{start_date}_{end_date}.csv"

    def _get_filepath(self, symbol: str, interval: str, start_date: str, end_date: str) -> Path:
        """Get full path to data file.

        Args:
            symbol: Trading pair
            interval: Candle interval
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)

        Returns:
            Path object
        """
        filename = self._generate_filename(symbol, interval, start_date, end_date)
        return self.data_dir / filename

    def save_to_csv(self, df: pd.DataFrame, filepath: Path) -> None:
        """Save DataFrame to CSV file.

        Args:
            df: DataFrame with OHLCV data
            filepath: Path to save file
        """
        # Prepare data for saving
        df_save = df.copy()

        # Convert timestamps to ISO format if they are datetime objects
        if pd.api.types.is_datetime64_any_dtype(df_save["open_time"]):
            df_save["timestamp"] = df_save["open_time"].dt.strftime("%Y-%m-%d %H:%M:%S")
        else:
            df_save["timestamp"] = df_save["open_time"]

        # Select and rename columns for standard OHLCV format
        df_save = df_save[["timestamp", "open", "high", "low", "close", "volume"]].copy()

        # Save to CSV
        df_save.to_csv(filepath, index=False)
        logger.info(f"Saved {len(df_save)} rows to {filepath}")

    def load_from_csv(self, filepath: Path, chunksize: int | None = None) -> pd.DataFrame:
        """Load DataFrame from CSV file with optional chunked reading.

        Args:
            filepath: Path to CSV file
            chunksize: Number of rows per chunk (None = load all at once)
                      Recommended: 50000 for large files to reduce memory usage

        Returns:
            DataFrame with OHLCV data
        """
        if chunksize is None:
            # Load entire file at once (backward compatible)
            df = pd.read_csv(filepath)
            logger.info(f"Loaded {len(df)} rows from {filepath}")
            return df

        # Chunked reading for large files
        logger.info(f"Loading {filepath} in chunks of {chunksize} rows")
        chunks = []
        total_rows = 0

        for chunk in pd.read_csv(filepath, chunksize=chunksize):
            chunks.append(chunk)
            total_rows += len(chunk)

        df = pd.concat(chunks, ignore_index=True)
        logger.info(f"Loaded {total_rows} rows from {filepath} using chunked reading")
        return df

    def check_data_coverage(self, filepath: Path, start_date: str, end_date: str) -> bool:
        """Check if existing file covers the requested date range.

        Optimized to only read first and last rows instead of entire file.

        Args:
            filepath: Path to existing CSV file
            start_date: Requested start date (YYYY-MM-DD)
            end_date: Requested end date (YYYY-MM-DD)

        Returns:
            True if file covers the range, False otherwise
        """
        if not filepath.exists():
            return False

        try:
            # Read only first row to get start timestamp (memory efficient)
            df_head = pd.read_csv(filepath, nrows=1)
            if df_head.empty:
                return False

            # Read last few rows to get end timestamp
            # Use chunked reading in reverse to find last valid row
            df_tail = pd.read_csv(filepath, skiprows=lambda i: i > 0 and i < self._get_file_row_count(filepath) - 1)
            if df_tail.empty:
                return False

            # Parse timestamps
            file_start = pd.to_datetime(df_head["timestamp"].iloc[0])
            file_end = pd.to_datetime(df_tail["timestamp"].iloc[-1])

            # Parse requested dates
            req_start = pd.to_datetime(start_date)
            req_end = pd.to_datetime(end_date)

            # Check coverage (allowing some tolerance for intraday data)
            return file_start <= req_start and file_end >= req_end

        except (IOError, OSError, ValueError, KeyError) as e:
            # File I/O errors, parsing errors, or missing columns
            logger.error(f"Error checking data coverage: {e}")
            return False
        except pd.errors.ParserError as e:
            # Pandas CSV parsing errors
            logger.error(f"CSV parsing error checking data coverage: {e}")
            return False

    def _get_file_row_count(self, filepath: Path) -> int:
        """Get row count of CSV file efficiently.

        Args:
            filepath: Path to CSV file

        Returns:
            Number of rows (excluding header)
        """
        with open(filepath, 'r') as f:
            return sum(1 for _ in f) - 1  # -1 for header

    def merge_and_update(self, existing_df: pd.DataFrame, new_df: pd.DataFrame) -> pd.DataFrame:
        """Merge existing and new data, removing duplicates.

        Args:
            existing_df: Existing DataFrame
            new_df: New DataFrame to merge

        Returns:
            Merged DataFrame
        """
        # Concatenate
        merged = pd.concat([existing_df, new_df], ignore_index=True)

        # Remove duplicates based on timestamp
        merged = merged.drop_duplicates(subset=["timestamp"], keep="last")

        # Sort by timestamp
        merged = merged.sort_values("timestamp").reset_index(drop=True)

        logger.info(f"Merged data: {len(merged)} total rows")
        return merged

    def get_or_download_data(
        self, symbol: str, interval: str, start_date: str, end_date: str, force_download: bool = False
    ) -> tuple[Path, int]:
        """Get data from cache or download if needed.

        Args:
            symbol: Trading pair
            interval: Candle interval
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            force_download: Force re-download even if file exists

        Returns:
            Tuple of (filepath, row_count)

        Raises:
            ValueError: If download fails
        """
        filepath = self._get_filepath(symbol, interval, start_date, end_date)

        # Check if file exists and covers the range
        if not force_download and self.check_data_coverage(filepath, start_date, end_date):
            logger.info(f"Using cached data from {filepath}")
            df = self.load_from_csv(filepath)
            return filepath, len(df)

        # Download fresh data
        logger.info(f"Downloading data for {symbol} {interval} from {start_date} to {end_date}")
        df = fetch_klines_archive(symbol, interval, start_date, end_date)

        # Save to CSV
        self.save_to_csv(df, filepath)

        return filepath, len(df)


# Global instance
_data_manager = DataManager()


def get_data_manager() -> DataManager:
    """Get global DataManager instance.

    Returns:
        DataManager instance
    """
    return _data_manager
