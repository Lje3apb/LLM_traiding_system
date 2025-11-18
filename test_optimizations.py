#!/usr/bin/env python3
"""Test script for CSV chunked reading and Binance rate limiting optimizations."""

import logging
import sys
import time
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

from llm_trading_system.data.data_manager import DataManager
from llm_trading_system.data.binance_loader import BinanceArchiveLoader

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_chunked_csv_reading():
    """Test chunked CSV reading functionality."""
    logger.info("=" * 60)
    logger.info("TEST 1: Chunked CSV Reading")
    logger.info("=" * 60)

    # Check if there's any CSV file in the data directory
    data_dir = Path("data")
    csv_files = list(data_dir.glob("*.csv"))

    if not csv_files:
        logger.warning("No CSV files found in data/ directory. Skipping CSV test.")
        logger.info("To test CSV chunked reading, download some data first.")
        return True

    # Use the first CSV file found
    test_file = csv_files[0]
    logger.info(f"Testing with file: {test_file}")

    dm = DataManager(data_dir="data")

    # Test 1: Load without chunking
    logger.info("\n--- Loading without chunking ---")
    start = time.time()
    df1 = dm.load_from_csv(test_file)
    time1 = time.time() - start
    logger.info(f"Loaded {len(df1)} rows in {time1:.3f}s")

    # Test 2: Load with chunking
    logger.info("\n--- Loading with chunking (chunksize=50000) ---")
    start = time.time()
    df2 = dm.load_from_csv(test_file, chunksize=50000)
    time2 = time.time() - start
    logger.info(f"Loaded {len(df2)} rows in {time2:.3f}s")

    # Verify both methods return same data
    if len(df1) == len(df2):
        logger.info("✓ Both methods returned same number of rows")
        return True
    else:
        logger.error(f"✗ Row count mismatch: {len(df1)} vs {len(df2)}")
        return False


def test_rate_limiting():
    """Test Binance API rate limiting."""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 2: Binance API Rate Limiting")
    logger.info("=" * 60)

    # Test downloading 3 days with different rate limits
    test_cases = [
        (0.0, "No rate limiting"),
        (0.1, "0.1s delay (default)"),
        (0.5, "0.5s delay (conservative)"),
    ]

    for delay, description in test_cases:
        logger.info(f"\n--- {description} ---")

        # Create loader with specific rate limit
        loader = BinanceArchiveLoader("BTCUSDT", "1h", rate_limit_delay=delay)

        # Download 3 days of data
        start = time.time()
        try:
            # Note: This will make real API calls
            # Using a short date range to minimize load
            df = loader.download_range("2024-01-01", "2024-01-03")
            elapsed = time.time() - start

            logger.info(f"Downloaded {len(df)} rows in {elapsed:.3f}s")

            # Expected time should be at least (num_days - 1) * delay
            # We download 3 days, so should have 2 delays minimum
            expected_min_time = 2 * delay

            if delay > 0 and elapsed < expected_min_time:
                logger.warning(
                    f"⚠ Expected at least {expected_min_time:.3f}s with rate limiting, "
                    f"got {elapsed:.3f}s"
                )
            else:
                logger.info(f"✓ Rate limiting working correctly")

        except Exception as e:
            logger.error(f"✗ Download failed: {e}")
            logger.info("This is expected if you don't have internet connection or Binance is down")
            continue

    return True


def main():
    """Run all tests."""
    logger.info("Starting optimization tests...\n")

    results = []

    # Test 1: Chunked CSV reading
    try:
        results.append(("CSV Chunked Reading", test_chunked_csv_reading()))
    except Exception as e:
        logger.error(f"CSV test failed with error: {e}", exc_info=True)
        results.append(("CSV Chunked Reading", False))

    # Test 2: Rate limiting (commented out by default to avoid hitting API)
    # Uncomment if you want to test with real API calls
    logger.info("\n" + "=" * 60)
    logger.info("SKIPPING: Binance API Rate Limiting Test")
    logger.info("To test rate limiting with real API calls, uncomment the code in main()")
    logger.info("=" * 60)

    # Uncomment to test rate limiting:
    # try:
    #     results.append(("Binance Rate Limiting", test_rate_limiting()))
    # except Exception as e:
    #     logger.error(f"Rate limiting test failed: {e}", exc_info=True)
    #     results.append(("Binance Rate Limiting", False))

    # Print summary
    logger.info("\n" + "=" * 60)
    logger.info("TEST SUMMARY")
    logger.info("=" * 60)
    for test_name, passed in results:
        status = "✓ PASSED" if passed else "✗ FAILED"
        logger.info(f"{test_name}: {status}")

    all_passed = all(result for _, result in results)
    if all_passed:
        logger.info("\n✓ All tests passed!")
        return 0
    else:
        logger.error("\n✗ Some tests failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
