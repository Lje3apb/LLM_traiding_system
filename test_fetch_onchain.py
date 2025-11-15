"""Simple test to verify fetch_onchain_data function works."""

import logging

from market_snapshot import Settings, fetch_onchain_data


def main() -> None:
    """Test fetch_onchain_data function."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    print("="*70)
    print("TESTING fetch_onchain_data() FUNCTION")
    print("="*70)

    # Create settings with free API endpoints
    settings = Settings(
        base_asset="BTCUSDT",
        horizon_hours=4,
        binance_base_url="https://api.binance.com",
        binance_fapi_url="https://fapi.binance.com",
        coinmetrics_base_url="https://community-api.coinmetrics.io/v4",
        blockchain_com_base_url="https://api.blockchain.info",
        cryptopanic_api_key=None,
        cryptopanic_base_url="https://cryptopanic.com/api/v1",
        newsapi_key=None,
        newsapi_base_url="https://newsapi.org/v2",
    )

    print("\nFetching on-chain data...")
    result = fetch_onchain_data(settings)

    print("\n" + "="*70)
    print("RESULTS")
    print("="*70)

    for key, value in result.items():
        if value is not None:
            if isinstance(value, float):
                print(f"✅ {key:35s}: {value:+.6f}")
            else:
                print(f"✅ {key:35s}: {value}")
        else:
            print(f"⚠️  {key:35s}: None (not available)")

    print("\n" + "="*70)

    # Check what we got
    has_addresses = result["active_addresses_vs_30d"] is not None
    has_stablecoins = result["stablecoin_supply_change_pct"] is not None

    if has_addresses and has_stablecoins:
        print("✅ SUCCESS: Got both address metrics and stablecoin data")
        print("   The function works correctly with free APIs!")
    elif has_addresses:
        print("✅ PARTIAL: Got address metrics")
        print("⚠️  Stablecoin data not available")
    elif has_stablecoins:
        print("✅ PARTIAL: Got stablecoin data")
        print("⚠️  Address metrics not available")
    else:
        print("❌ FAILED: No data retrieved")
        print("   Check your internet connection and API availability")

    print("="*70)


if __name__ == "__main__":
    main()
