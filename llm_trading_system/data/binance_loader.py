"""Reliable Binance archive data downloader."""

from __future__ import annotations

import io
import logging
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests
from tenacity import retry, stop_after_attempt, wait_exponential

# Binance archive URL
BINANCE_ARCHIVE_URL = "https://data.binance.vision/data/spot/daily/klines"

# Setup logging
logger = logging.getLogger(__name__)


class BinanceArchiveLoader:
    """Reliable loader for data.binance.vision archive with rate limiting."""

    def __init__(self, symbol: str, interval: str, rate_limit_delay: float = 0.1) -> None:
        """Initialize loader.

        Args:
            symbol: Trading pair (e.g. BTCUSDT)
            interval: Candle interval (1m, 5m, 15m, 1h, 4h, 1d, etc.)
            rate_limit_delay: Delay in seconds between API requests (default: 0.1)
                             Recommended: 0.1-0.5 to avoid overwhelming the API
        """
        self.symbol = symbol.upper()
        self.interval = interval
        self.base_url = BINANCE_ARCHIVE_URL
        self.rate_limit_delay = rate_limit_delay

    def _build_url(self, date: datetime) -> str:
        """Build URL for specific date.

        Args:
            date: Date to download

        Returns:
            Archive URL
        """
        date_str = date.strftime("%Y-%m-%d")
        return f"{self.base_url}/{self.symbol}/{self.interval}/{self.symbol}-{self.interval}-{date_str}.zip"

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _download_day(self, date: datetime) -> pd.DataFrame | None:
        """Download data for one day.

        Args:
            date: Date to download

        Returns:
            DataFrame with data or None if not found
        """
        url = self._build_url(date)
        logger.debug(f"Downloading: {url}")

        try:
            response = requests.get(url, timeout=60, stream=True)

            if response.status_code == 404:
                logger.warning(f"Data not found for {date.date()}")
                return None

            response.raise_for_status()

            # Read ZIP archive
            with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
                csv_name = zf.namelist()[0]
                with zf.open(csv_name) as csv_file:
                    df = pd.read_csv(
                        csv_file,
                        header=None,
                        names=[
                            "open_time",
                            "open",
                            "high",
                            "low",
                            "close",
                            "volume",
                            "close_time",
                            "quote_volume",
                            "trades",
                            "taker_buy_base",
                            "taker_buy_quote",
                            "ignore",
                        ],
                    )

                    df = df.drop(columns=["ignore"])

                    # Check if dataframe is empty
                    if df.empty:
                        logger.warning(f"Downloaded empty file for {date.date()}")
                        return None

                    # Convert timestamps to numeric type
                    df["open_time"] = pd.to_numeric(df["open_time"], errors="coerce")
                    df["close_time"] = pd.to_numeric(df["close_time"], errors="coerce")

                    # Remove rows with NaN timestamps
                    nan_mask = df["open_time"].isna() | df["close_time"].isna()
                    if nan_mask.any():
                        logger.warning(
                            f"Found {nan_mask.sum()} rows with non-numeric timestamps for {date.date()}, "
                            f"removing them"
                        )
                        df = df[~nan_mask]

                    if df.empty:
                        logger.warning(f"All rows had non-numeric timestamps for {date.date()}")
                        return None

                    # Check timestamp scale (microseconds vs milliseconds)
                    # If timestamps are in microseconds (> 10^13), convert to milliseconds
                    if df["open_time"].iloc[0] > 10**13:
                        logger.debug(f"Converting timestamps from microseconds to milliseconds for {date.date()}")
                        df["open_time"] = df["open_time"] // 1000
                        df["close_time"] = df["close_time"] // 1000

                    # Validate timestamp range (2009-2100)
                    min_valid_ts = 1230768000000  # 2009-01-01
                    max_valid_ts = 4102444800000  # 2100-01-01

                    invalid_rows = (
                        (df["open_time"] < min_valid_ts)
                        | (df["open_time"] > max_valid_ts)
                        | (df["close_time"] < min_valid_ts)
                        | (df["close_time"] > max_valid_ts)
                    )

                    if invalid_rows.any():
                        logger.warning(
                            f"Found {invalid_rows.sum()} rows with invalid timestamp range for {date.date()}, "
                            f"removing them"
                        )
                        df = df[~invalid_rows]

                    if df.empty:
                        logger.warning(f"All rows had invalid timestamps for {date.date()}")
                        return None

                    # Convert to datetime
                    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
                    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)

                    logger.info(f"Downloaded {len(df)} rows for {date.date()}")
                    return df

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                logger.warning(f"Data not found for {date.date()}")
                return None
            logger.error(f"HTTP error for {date.date()}: {e}")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error for {date.date()}: {e}")
            raise
        except Exception as e:
            # Only log full stack trace in DEBUG mode to avoid exposing internals
            logger.error(
                f"Unexpected error for {date.date()}: {e}",
                exc_info=(logger.level == logging.DEBUG)
            )
            return None

    def download_range(
        self, start_date: str, end_date: str, progress_callback=None
    ) -> pd.DataFrame:
        """Download data for date range with rate limiting.

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            progress_callback: Optional callback function(current, total, date_str, filename)

        Returns:
            Combined DataFrame

        Raises:
            ValueError: If no data downloaded
        """
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")

        dates = [start + timedelta(days=i) for i in range((end - start).days + 1)]
        logger.info(
            f"Downloading {len(dates)} days: {start_date} to {end_date} "
            f"(rate limit: {self.rate_limit_delay}s between requests)"
        )

        dfs = []
        for idx, date in enumerate(dates, 1):
            try:
                # Call progress callback if provided
                if progress_callback:
                    date_str = date.strftime("%Y-%m-%d")
                    filename = f"{self.symbol}-{self.interval}-{date_str}.zip"
                    progress_callback(idx, len(dates), date_str, filename)

                df = self._download_day(date)
                if df is not None:
                    dfs.append(df)

                # Rate limiting: add delay between requests (except for last request)
                if idx < len(dates) and self.rate_limit_delay > 0:
                    time.sleep(self.rate_limit_delay)

            except Exception as e:
                logger.error(f"Failed to download {date.date()}: {e}")
                # Still apply rate limit even on error to avoid hammering the API
                if idx < len(dates) and self.rate_limit_delay > 0:
                    time.sleep(self.rate_limit_delay)
                continue

        if not dfs:
            raise ValueError(f"No data downloaded for {self.symbol} {self.interval}")

        # Concatenate all dataframes
        df = pd.concat(dfs, ignore_index=True)
        df = df.sort_values("open_time").reset_index(drop=True)

        # Remove duplicates based on open_time
        df = df.drop_duplicates(subset=["open_time"], keep="first")

        logger.info(f"Total downloaded: {len(df)} rows")
        return df


def fetch_klines_archive(
    symbol: str, interval: str, start_date: str, end_date: str, rate_limit_delay: float = 0.1
) -> pd.DataFrame:
    """Convenient function for downloading data (synchronous).

    Args:
        symbol: Trading pair
        interval: Candle interval
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        rate_limit_delay: Delay in seconds between API requests (default: 0.1)

    Returns:
        DataFrame with historical data
    """
    loader = BinanceArchiveLoader(symbol, interval, rate_limit_delay=rate_limit_delay)
    return loader.download_range(start_date, end_date)
