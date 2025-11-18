#!/usr/bin/env python3
"""Full cycle integration script for manual runs."""

import logging
import os
from pathlib import Path
from typing import Any, Dict

from llm_trading_system.core.market_snapshot import (
    build_market_snapshot,
    load_settings,
)
from llm_trading_system.core.regime_engine import evaluate_regime_and_size
from llm_trading_system.infra.llm_infra import LLMClientSync, OllamaProvider, RetryPolicy


# Load .env file if it exists
def load_env() -> None:
    """Load environment variables from .env file."""
    env_file = Path(__file__).parent.parent.parent / ".env"
    if env_file.exists():
        with open(env_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip()
                    if key and value:
                        os.environ[key] = value


def create_mock_snapshot() -> Dict[str, Any]:
    """Create a mock market snapshot for testing without API calls."""
    return {
        "timestamp_utc": "2025-01-15T10:30:00+00:00",
        "base_asset": "BTCUSDT",
        "horizon_hours": 4,
        "market": {
            "spot_price": 45230.50,
            "change_24h_pct": 2.35,
            "volume_24h_usd": 28_500_000_000,
            "realized_vol": 0.58,
            "funding_rate": 0.00012,
            "open_interest": 12_500_000_000,
            "btc_dominance": 52.3,
            "stablecoin_flows_ex": 450_000_000,
            "perp_spot_basis_bps": 3.2,
            "spread_bps": 1.2,
            "ob_imbalance": 0.15,
        },
        "onchain": {
            "exchange_netflows_btc": -2500,
            "whale_transfers": None,
            "new_addresses_vs_30d": 0.08,
            "active_addresses_vs_30d": 0.12,
            "stablecoin_supply_change_pct": 0.015,
        },
        "news": [
            {
                "source": "CryptoNews",
                "time_utc": "2025-01-15T09:15:00+00:00",
                "sentiment": 0.6,
                "impact_score": 0.7,
                "text": "Major institutional investor announces $500M BTC allocation",
            },
            {
                "source": "Bloomberg",
                "time_utc": "2025-01-15T08:30:00+00:00",
                "sentiment": 0.3,
                "impact_score": 0.5,
                "text": "Bitcoin network hashrate reaches new all-time high",
            },
            {
                "source": "Reuters",
                "time_utc": "2025-01-15T07:45:00+00:00",
                "sentiment": -0.2,
                "impact_score": 0.4,
                "text": "Regulatory concerns in emerging markets cause minor volatility",
            },
        ],
        "macro_context": "Global markets showing positive sentiment, equity indices at monthly highs",
    }


load_env()


def run_full_cycle_test(
    use_real_data: bool = False,
    ollama_model: str | None = None,
    ollama_url: str | None = None,
) -> None:
    """Run complete trading system test from data collection to position sizing.

    Args:
        use_real_data: If True, fetch real market data; otherwise use mock data
        ollama_model: Override default model from config (optional)
        ollama_url: Override default Ollama URL from config (optional)
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    # Load unified configuration
    from llm_trading_system.config.service import load_config
    cfg = load_config()

    print("=" * 80)
    print("FULL CYCLE INTEGRATION TEST")
    print("=" * 80)
    print()

    # =========================================================================
    # STEP 1: Collect Market Data
    # =========================================================================
    print("[STEP 1] Collecting market data...")
    print("-" * 80)

    if use_real_data:
        print("Fetching REAL market data from APIs...")
        settings = load_settings()
        snapshot = build_market_snapshot(settings)
        horizon_hours = settings.horizon_hours
        base_asset = settings.base_asset
    else:
        print("Using MOCK market data for testing...")
        snapshot = create_mock_snapshot()
        horizon_hours = snapshot["horizon_hours"]
        base_asset = snapshot["base_asset"]

    print(f"✓ Data collected for {base_asset}, horizon: {horizon_hours}h")
    print(f"  Timestamp: {snapshot['timestamp_utc']}")
    print(f"  Spot price: {snapshot['market'].get('spot_price', 'N/A')}")
    print(f"  24h change: {snapshot['market'].get('change_24h_pct', 'N/A')}%")
    print(f"  News items: {len(snapshot.get('news', []))}")
    print()

    # =========================================================================
    # STEP 2: Initialize LLM infrastructure
    # =========================================================================
    print("[STEP 2] Initializing LLM infrastructure...")
    print("-" * 80)

    # Use provided values or fall back to config
    model = ollama_model or cfg.llm.default_model
    base_url = ollama_url or cfg.llm.ollama_base_url
    temperature = cfg.llm.temperature
    timeout = cfg.llm.timeout_seconds

    print(f"Model: {model}")
    print(f"Endpoint: {base_url}")
    print(f"Temperature: {temperature}")
    print(f"Timeout: {timeout}s")

    # Load risk config
    base_size = cfg.risk.base_long_size  # Use config value
    k_max = cfg.risk.k_max

    try:
        provider = OllamaProvider(base_url=base_url, model=model, timeout=timeout)
        retry_policy = RetryPolicy(max_retries=2, base_delay=2.0)
        client = LLMClientSync(provider=provider, retry_policy=retry_policy)

        print("Waiting for LLM response (this may take 10-60 seconds)...")
        result = evaluate_regime_and_size(
            snapshot=snapshot,
            client=client,
            base_size=base_size,
            k_max=k_max,
            temperature=temperature,
        )

        llm_output = result["llm_output"]
        k_long = result["k_long"]
        k_short = result["k_short"]
        pos_long = result["pos_long"]
        pos_short = result["pos_short"]

        print("✓ Received response from LLM and computed sizing")
        print()

    except Exception as exc:  # pragma: no cover - manual run diagnostic info
        print(f"✗ LLM request failed: {exc}")
        print()
        print("Possible issues:")
        print("1. Ollama service not running (run: ollama serve)")
        print(f"2. Model '{ollama_model}' not available (run: ollama pull {ollama_model})")
        print("3. Timeout (try smaller model or increase timeout)")
        print("4. Network or SSL issues")
        return

    # =========================================================================
    # STEP 3: Summarize LLM Response
    # =========================================================================
    print("[STEP 3] LLM regime summary...")
    print("-" * 80)
    print(f"  Regime: {llm_output.get('regime_label', 'N/A')}")
    print(f"  Confidence: {llm_output.get('confidence_level', 'N/A')}")
    print(f"  Bull probability: {llm_output.get('prob_bull', 0):.2%}")
    print(f"  Bear probability: {llm_output.get('prob_bear', 0):.2%}")
    print()

    # =========================================================================
    # STEP 4: Calculate Position Sizing
    # =========================================================================
    print("[STEP 4] Position sizing overview...")
    print("-" * 80)
    print(f"  Long multiplier (k_long):  {k_long:.4f}")
    print(f"  Short multiplier (k_short): {k_short:.4f}")
    print(f"  Long position size:  {pos_long:.6f} ({pos_long * 100:.2f}% capital)")
    print(f"  Short position size: {pos_short:.6f} ({pos_short * 100:.2f}% capital)")
    print()

    # =========================================================================
    # STEP 5: Display Final Results
    # =========================================================================
    print("=" * 80)
    print("FINAL RESULTS")
    print("=" * 80)
    print()

    print(f"Asset: {base_asset}")
    print(f"Timestamp: {llm_output.get('timestamp_utc', 'N/A')}")
    print(f"Horizon: {horizon_hours} hours")
    print()

    print("REGIME ASSESSMENT:")
    print(f"  Regime:      {llm_output.get('regime_label', 'N/A').upper()}")
    print(f"  Confidence:  {llm_output.get('confidence_level', 'N/A').upper()}")
    print(f"  Bull prob:   {llm_output.get('prob_bull', 0):.1%}")
    print(f"  Bear prob:   {llm_output.get('prob_bear', 0):.1%}")
    print()

    scores = llm_output.get("scores", {})
    print("MARKET SCORES:")
    print(f"  Global sentiment:   {scores.get('global_sentiment', 0):+.2f}")
    print(f"  BTC sentiment:      {scores.get('btc_sentiment', 0):+.2f}")
    print(f"  Onchain pressure:   {scores.get('onchain_pressure', 0):+.2f}")
    print(f"  Trend strength:     {scores.get('trend_strength', 0):.2f}")
    print(f"  Liquidity risk:     {scores.get('liquidity_risk', 0):.2f}")
    print(f"  News risk:          {scores.get('news_risk', 0):.2f}")
    print()

    print("POSITION SIZING:")
    print(f"  Base size:          {base_size * 100:.1f}% capital (from config)")
    print(f"  K_max:              {k_max:.2f}x (from config)")
    print(f"  Long multiplier:    {k_long:.4f}x")
    print(f"  Short multiplier:   {k_short:.4f}x")
    print(f"  → LONG position:    {pos_long * 100:.2f}% capital")
    print(f"  → SHORT position:   {pos_short * 100:.2f}% capital")
    print()

    reasoning = llm_output.get("reasoning_short", "N/A")
    print("REASONING:")
    print(f"  {reasoning}")
    print()

    factors = llm_output.get("factors_summary", [])
    if factors:
        print("KEY FACTORS:")
        for idx, factor in enumerate(factors, start=1):
            print(f"  {idx}. {factor}")
        print()

    print("=" * 80)
    print("TRADING RECOMMENDATION:")
    print("=" * 80)

    if k_long > 1.2:
        recommendation = f"FAVOR LONG positions (multiplier: {k_long:.2f}x)"
    elif k_short > 1.2:
        recommendation = f"FAVOR SHORT positions (multiplier: {k_short:.2f}x)"
    elif max(k_long, k_short) < 0.5:
        recommendation = "AVOID TRADING (high risk detected)"
    else:
        recommendation = "NEUTRAL - no strong directional edge"

    print(recommendation)
    print("=" * 80)
    print()
    print("✓ Full cycle test completed successfully!")
    print()


def main() -> None:
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Full cycle integration test for trading system"
    )
    parser.add_argument(
        "--real-data",
        action="store_true",
        help="Use real market data (requires API keys in .env)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="gpt-oss:20b",
        help="Ollama model name (default: gpt-oss:20b)",
    )
    parser.add_argument(
        "--ollama-url",
        type=str,
        default="http://localhost:11434",
        help="Ollama API URL (default: http://localhost:11434)",
    )

    args = parser.parse_args()

    run_full_cycle_test(
        use_real_data=args.real_data,
        ollama_model=args.model,
        ollama_url=args.ollama_url,
    )


if __name__ == "__main__":
    main()
