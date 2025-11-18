#!/usr/bin/env python3
"""Simple test script to verify AppConfig service functionality."""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


def test_config_service():
    """Test basic configuration service operations."""
    print("=" * 80)
    print("Testing AppConfig Service")
    print("=" * 80)
    print()

    # Test 1: Import
    print("[Test 1] Importing configuration service...")
    try:
        from llm_trading_system.config import (
            load_config,
            save_config,
            get_config_path,
        )
        print("✓ Import successful")
    except ImportError as e:
        print(f"✗ Import failed: {e}")
        return False
    print()

    # Test 2: Get config path
    print("[Test 2] Getting config path...")
    try:
        config_path = get_config_path()
        print(f"✓ Config path: {config_path}")
    except Exception as e:
        print(f"✗ Failed: {e}")
        return False
    print()

    # Test 3: Load config
    print("[Test 3] Loading configuration...")
    try:
        cfg = load_config()
        print("✓ Config loaded successfully")
        print(f"  - Config file exists: {config_path.exists()}")
    except Exception as e:
        print(f"✗ Failed: {e}")
        return False
    print()

    # Test 4: Access config values
    print("[Test 4] Accessing config values...")
    try:
        print(f"  API:")
        print(f"    - binance_base_url: {cfg.api.binance_base_url}")
        print(f"    - newsapi_key: {cfg.api.newsapi_key or 'Not set'}")
        print()
        print(f"  LLM:")
        print(f"    - provider: {cfg.llm.llm_provider}")
        print(f"    - default_model: {cfg.llm.default_model}")
        print(f"    - ollama_base_url: {cfg.llm.ollama_base_url}")
        print(f"    - temperature: {cfg.llm.temperature}")
        print(f"    - timeout: {cfg.llm.timeout_seconds}s")
        print()
        print(f"  Market:")
        print(f"    - base_asset: {cfg.market.base_asset}")
        print(f"    - horizon_hours: {cfg.market.horizon_hours}")
        print(f"    - use_news: {cfg.market.use_news}")
        print()
        print(f"  Risk:")
        print(f"    - base_long_size: {cfg.risk.base_long_size}")
        print(f"    - k_max: {cfg.risk.k_max}")
        print(f"    - edge_gain: {cfg.risk.edge_gain}")
        print(f"    - edge_gamma: {cfg.risk.edge_gamma}")
        print()
        print(f"  Exchange:")
        print(f"    - exchange_name: {cfg.exchange.exchange_name}")
        print(f"    - use_testnet: {cfg.exchange.use_testnet}")
        print(f"    - live_trading_enabled: {cfg.exchange.live_trading_enabled}")
        print()
        print(f"  UI:")
        print(f"    - default_initial_deposit: {cfg.ui.default_initial_deposit}")
        print(f"    - default_commission: {cfg.ui.default_commission}%")
        print("✓ All config sections accessible")
    except Exception as e:
        print(f"✗ Failed: {e}")
        return False
    print()

    # Test 5: Modify and save
    print("[Test 5] Testing save functionality...")
    try:
        # Save current config to ensure file exists
        save_config(cfg)
        print(f"✓ Config saved to {config_path}")
    except Exception as e:
        print(f"✗ Failed to save: {e}")
        return False
    print()

    # Test 6: Integration with market_snapshot
    print("[Test 6] Testing integration with market_snapshot...")
    try:
        from llm_trading_system.core.market_snapshot import load_settings

        settings = load_settings()
        print("✓ load_settings() works with AppConfig")
        print(f"  - base_asset: {settings.base_asset}")
        print(f"  - horizon_hours: {settings.horizon_hours}")
    except Exception as e:
        print(f"✗ Failed: {e}")
        return False
    print()

    print("=" * 80)
    print("All tests passed!")
    print("=" * 80)
    print()
    print("Next steps:")
    print(f"1. Edit config file: {config_path}")
    print("2. Run your trading system - it will use the new config")
    print("3. Config changes persist between runs")
    print()

    return True


if __name__ == "__main__":
    success = test_config_service()
    sys.exit(0 if success else 1)
