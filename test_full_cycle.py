#!/usr/bin/env python3
"""Full cycle integration test for LLM Trading System.

This script demonstrates the complete pipeline from data collection to position sizing:
1. Collect market data (real or mock)
2. Build LLM prompts
3. Query LLM for regime assessment
4. Calculate position sizing
5. Display trading recommendation

Usage:
    python test_full_cycle.py [OPTIONS]

Options:
    --real-data              Use real data from APIs (requires API keys)
    --model MODEL            Ollama model name (default: llama3.2)
    --ollama-url URL         Ollama API URL (default: http://localhost:11434)
    -h, --help               Show this help message
"""

import argparse
import json
import sys
from typing import Any, Dict

# Import from project
from llm_trading_system.core.market_snapshot import (
    build_market_snapshot,
    build_system_prompt,
    build_user_prompt,
    load_settings,
)
from llm_trading_system.core.position_sizing import compute_position_multipliers
from llm_trading_system.infra.llm_infra.providers_ollama import OllamaProvider


def make_mock_snapshot() -> Dict[str, Any]:
    """Create mock market snapshot for testing without real API calls."""
    return {
        "timestamp_utc": "2025-01-18T10:30:00+00:00",
        "base_asset": "BTCUSDT",
        "horizon_hours": 4,
        "market": {
            "spot_price": 45230.5,
            "change_24h_pct": 2.35,
            "volume_24h_usd": 18_500_000_000,
            "realized_vol": 0.45,
            "funding_rate": 0.00015,
            "open_interest": 6_200_000_000,
            "btc_dominance": 52.3,
            "stablecoin_flows_ex": 250_000_000,
            "perp_spot_basis_bps": 3.2,
            "spread_bps": 0.75,
            "ob_imbalance": 0.15,
        },
        "onchain": {
            "exchange_netflows_btc": -1500,
            "whale_transfers": None,
            "new_addresses_vs_30d": 0.08,
            "active_addresses_vs_30d": 0.12,
            "stablecoin_supply_change_pct": 0.025,
        },
        "news": [
            {
                "source": "CryptoPanic",
                "time_utc": "2025-01-18T09:00:00+00:00",
                "sentiment": 0.6,
                "impact_score": 0.7,
                "text": "Major institutional BTC allocation announced - positive market reaction",
            },
            {
                "source": "NewsAPI",
                "time_utc": "2025-01-18T08:30:00+00:00",
                "sentiment": 0.4,
                "impact_score": 0.5,
                "text": "Network hashrate reaches all-time high amid growing adoption",
            },
            {
                "source": "CryptoPanic",
                "time_utc": "2025-01-18T07:45:00+00:00",
                "sentiment": 0.3,
                "impact_score": 0.6,
                "text": "Stablecoin inflows to exchanges increasing - potential buying pressure",
            },
        ],
        "macro_context": "",
    }


def print_separator(char: str = "=", length: int = 80) -> None:
    """Print a separator line."""
    print(char * length)


def print_step_header(step: int, title: str) -> None:
    """Print formatted step header."""
    print()
    print(f"[STEP {step}] {title}")
    print_separator("-")


def main() -> int:
    """Main entry point for full cycle test."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="Full cycle integration test for LLM Trading System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--real-data",
        action="store_true",
        help="Use real data from APIs (requires API keys in environment)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="llama3.2",
        help="Ollama model name (default: llama3.2)",
    )
    parser.add_argument(
        "--ollama-url",
        type=str,
        default="http://localhost:11434",
        help="Ollama API URL (default: http://localhost:11434)",
    )
    args = parser.parse_args()

    # Print header
    print_separator("=")
    print("FULL CYCLE INTEGRATION TEST")
    print_separator("=")

    # STEP 1: Collect market data
    print_step_header(1, "Collecting market data...")

    if args.real_data:
        print("Using REAL market data from APIs...")
        try:
            settings = load_settings()
            snapshot = build_market_snapshot(settings)
            base_asset = settings.base_asset
            horizon_hours = settings.horizon_hours
        except Exception as e:
            print(f"✗ Failed to collect real data: {e}")
            print("  Falling back to mock data...")
            snapshot = make_mock_snapshot()
            base_asset = snapshot["base_asset"]
            horizon_hours = snapshot["horizon_hours"]
    else:
        print("Using MOCK market data for testing...")
        snapshot = make_mock_snapshot()
        base_asset = snapshot["base_asset"]
        horizon_hours = snapshot["horizon_hours"]

    print(f"✓ Data collected for {base_asset}, horizon: {horizon_hours}h")
    print(f"  Timestamp: {snapshot['timestamp_utc']}")
    print(f"  Spot price: {snapshot['market'].get('spot_price', 'N/A')}")
    print(f"  24h change: {snapshot['market'].get('change_24h_pct', 'N/A')}%")
    print(f"  News items: {len(snapshot.get('news', []))}")

    # STEP 2: Build prompts
    print_step_header(2, "Building prompts for LLM...")

    system_prompt = build_system_prompt()
    user_prompt = build_user_prompt(snapshot, horizon_hours, base_asset)

    print(f"✓ System prompt length: {len(system_prompt)} chars")
    print(f"✓ User prompt length: {len(user_prompt)} chars")

    # STEP 3: Query LLM
    print_step_header(3, "Sending request to LLM...")

    print(f"Model: {args.model}")
    print(f"Endpoint: {args.ollama_url}")
    print("Waiting for LLM response (this may take 10-60 seconds)...")

    try:
        client = OllamaProvider(
            base_url=args.ollama_url,
            model=args.model,
            timeout=120.0,
        )

        response = client.complete(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.1,
        )

        print("✓ Received response from LLM")
        print(f"  Response length: {len(response)} chars")
    except Exception as e:
        print(f"✗ Failed to get LLM response: {e}")
        print("\nTroubleshooting:")
        print("  1. Check that Ollama is running: ollama serve")
        print(f"  2. Check that model '{args.model}' is available: ollama list")
        print(f"  3. Pull model if needed: ollama pull {args.model}")
        return 1

    # STEP 4: Parse response
    print_step_header(4, "Parsing LLM response...")

    try:
        llm_output = json.loads(response)
        print("✓ Successfully parsed JSON response")
        print(f"  Regime: {llm_output.get('regime_label', 'N/A')}")
        print(f"  Confidence: {llm_output.get('confidence_level', 'N/A')}")
        print(f"  Bull probability: {llm_output.get('prob_bull', 0) * 100:.2f}%")
        print(f"  Bear probability: {llm_output.get('prob_bear', 0) * 100:.2f}%")
    except json.JSONDecodeError as e:
        print(f"✗ Failed to parse JSON: {e}")
        print(f"\nRaw response:\n{response[:500]}...")
        return 1

    # STEP 5: Calculate position sizing
    print_step_header(5, "Calculating position sizing...")

    base_size = 0.01  # 1% of capital
    k_max = 2.0

    try:
        pos_long, k_long, k_short = compute_position_multipliers(
            llm_output,
            side="long",
            base_long_size=base_size,
            base_short_size=base_size,
            k_max=k_max,
        )

        pos_short, _, _ = compute_position_multipliers(
            llm_output,
            side="short",
            base_long_size=base_size,
            base_short_size=base_size,
            k_max=k_max,
        )

        print("✓ Position sizing calculated (AGGRESSIVE mode)")
        print(f"  Long multiplier (k_long):  {k_long:.4f}")
        print(f"  Short multiplier (k_short): {k_short:.4f}")
        print(f"  Long position size:  {pos_long:.6f} ({pos_long * 100:.2f}% capital)")
        print(f"  Short position size: {pos_short:.6f} ({pos_short * 100:.2f}% capital)")
        print()
        print("Note: New aggressive position sizing with non-linear edge amplification")
        print(f"      Multipliers can now range from 0.0 to k_max (default {k_max})")
    except Exception as e:
        print(f"✗ Failed to calculate position sizing: {e}")
        return 1

    # FINAL RESULTS
    print()
    print_separator("=")
    print("FINAL RESULTS")
    print_separator("=")
    print()
    print(f"Asset: {base_asset}")
    print(f"Timestamp: {snapshot['timestamp_utc']}")
    print(f"Horizon: {horizon_hours} hours")
    print()
    print("REGIME ASSESSMENT:")
    print(f"  Regime:      {llm_output.get('regime_label', 'N/A').upper()}")
    conf_level = llm_output.get('confidence_level', 'N/A').upper()
    print(f"  Confidence:  {conf_level} (now encouraged: 0.6-0.85 probabilities)")
    print(f"  Bull prob:   {llm_output.get('prob_bull', 0) * 100:.1f}% (less conservative than before)")
    print(f"  Bear prob:   {llm_output.get('prob_bear', 0) * 100:.1f}%")
    print()
    print("MARKET SCORES:")
    scores = llm_output.get("scores", {})
    print(f"  Global sentiment:   {scores.get('global_sentiment', 0):+.2f}")
    print(f"  BTC sentiment:      {scores.get('btc_sentiment', 0):+.2f}")
    print(f"  Onchain pressure:   {scores.get('onchain_pressure', 0):+.2f}")
    print(f"  Trend strength:     {scores.get('trend_strength', 0):.2f}")
    print(f"  Liquidity risk:     {scores.get('liquidity_risk', 0):.2f}")
    print(f"  News risk:          {scores.get('news_risk', 0):.2f}")
    print()
    print("POSITION SIZING (AGGRESSIVE):")
    print(f"  Base size:          {base_size * 100:.1f}% capital")
    print(f"  Neutral baseline:   0.5 (BASE_K)")
    print(f"  Long multiplier:    {k_long:.2f}x (aggressive amplification)")
    print(f"  Short multiplier:   {k_short:.2f}x (strong directional bias)")
    print(f"  → LONG position:    {pos_long * 100:.2f}% capital")
    print(f"  → SHORT position:   {pos_short * 100:.2f}% capital")
    print()
    print("  Algorithm: edge_eff = (|prob_bull - 0.5| * 2.5) ^ 0.7")
    print("             edge_eff *= confidence_scale * trend_scale")
    print("             k_long = 0.5 + edge_eff (if bullish)")
    print("             k_short = 0.5 - edge_eff (if bullish)")
    print()
    print("REASONING:")
    print(f"  {llm_output.get('reasoning_short', 'N/A')}")
    print()
    print("KEY FACTORS:")
    for i, factor in enumerate(llm_output.get("factors_summary", []), 1):
        print(f"  {i}. {factor}")
    print()
    print_separator("=")
    print("TRADING RECOMMENDATION:")
    print_separator("=")

    if k_long > k_short:
        print(f"FAVOR LONG positions (multiplier: {k_long:.2f}x)")
        if k_short < 0.1:
            print(f"AVOID SHORT positions (multiplier: {k_short:.2f}x - strong bullish bias)")
    elif k_short > k_long:
        print(f"FAVOR SHORT positions (multiplier: {k_short:.2f}x)")
        if k_long < 0.1:
            print(f"AVOID LONG positions (multiplier: {k_long:.2f}x - strong bearish bias)")
    else:
        print("NEUTRAL - No clear directional bias")

    print_separator("=")
    print()
    print("NOTE: New aggressive regime estimator produces:")
    print("- More confident probabilities (0.6-0.85 instead of ~0.5)")
    print("- Non-linear position sizing amplification")
    print("- Stronger directional bias (shorts disabled in bull regime)")
    print()
    print("✓ Full cycle test completed successfully!")

    return 0


if __name__ == "__main__":
    sys.exit(main())
