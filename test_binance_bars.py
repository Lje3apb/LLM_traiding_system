#!/usr/bin/env python3
"""Test script to fetch recent bars from Binance API.

This script tests fetching 50 historical candlesticks from Binance
starting from the current moment, going backwards.
"""

import logging
from datetime import datetime, timedelta

import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def fetch_recent_klines(symbol: str = "BTCUSDT", interval: str = "1h", limit: int = 50):
    """Fetch recent klines from Binance API.

    Args:
        symbol: Trading pair (default: BTCUSDT)
        interval: Timeframe (default: 1h)
        limit: Number of candles to fetch (default: 50)

    Returns:
        List of klines or None on error
    """
    url = "https://api.binance.com/api/v3/klines"

    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }

    try:
        logger.info(f"Fetching {limit} recent {interval} bars for {symbol} from Binance...")
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()

        klines = response.json()

        if not klines:
            logger.error("No data returned from Binance")
            return None

        logger.info(f"Successfully fetched {len(klines)} bars")

        # Print first and last bar for verification
        if klines:
            first_bar = klines[0]
            last_bar = klines[-1]

            first_time = datetime.fromtimestamp(first_bar[0] / 1000)
            last_time = datetime.fromtimestamp(last_bar[0] / 1000)

            logger.info(f"First bar: {first_time} - O:{first_bar[1]} H:{first_bar[2]} L:{first_bar[3]} C:{first_bar[4]} V:{first_bar[5]}")
            logger.info(f"Last bar:  {last_time} - O:{last_bar[1]} H:{last_bar[2]} L:{last_bar[3]} C:{last_bar[4]} V:{last_bar[5]}")

            # Print all bars in detail
            print("\n" + "="*100)
            print(f"{'Timestamp':<20} {'Open':<12} {'High':<12} {'Low':<12} {'Close':<12} {'Volume':<15}")
            print("="*100)

            for bar in klines:
                timestamp = datetime.fromtimestamp(bar[0] / 1000)
                print(f"{timestamp.strftime('%Y-%m-%d %H:%M:%S'):<20} {float(bar[1]):<12.2f} {float(bar[2]):<12.2f} {float(bar[3]):<12.2f} {float(bar[4]):<12.2f} {float(bar[5]):<15.4f}")

            print("="*100)

        return klines

    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch data from Binance: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return None


if __name__ == "__main__":
    print("\n🔍 Testing Binance API - Fetching 50 recent 1h bars for BTCUSDT\n")

    klines = fetch_recent_klines(symbol="BTCUSDT", interval="1h", limit=50)

    if klines:
        print(f"\n✅ SUCCESS: Fetched {len(klines)} bars from Binance")
        print(f"📊 Data looks correct and complete")
    else:
        print("\n❌ FAILED: Could not fetch data from Binance")
        print("Check your internet connection or Binance API status")
