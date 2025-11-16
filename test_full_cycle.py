#!/usr/bin/env python3
"""Full cycle integration test: Data -> LLM -> Position Sizing.

This test demonstrates the complete trading system pipeline:
1. Collect market data (or use mock data)
2. Build prompts for LLM
3. Send request to LLM (Ollama)
4. Parse JSON response
5. Calculate position sizing
6. Display final trading decision
"""

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict

from llm_infra import OllamaProvider, LLMClientSync, RetryPolicy
from position_sizing import compute_position_multipliers
from market_snapshot import (
    build_market_snapshot,
    build_system_prompt,
    build_user_prompt,
    load_settings,
)


# Load .env file if it exists
def load_env():
    """Load environment variables from .env file."""
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip()
                    if key and value:
                        os.environ[key] = value


load_env()


def parse_llm_response(response_text: str) -> Dict[str, Any]:
    """Parse LLM JSON response with error handling.

    Args:
        response_text: Raw text response from LLM

    Returns:
        Parsed JSON dictionary

    Raises:
        ValueError: If response is not valid JSON
    """
    # Try to find JSON in the response (LLM might add extra text)
    response_text = response_text.strip()

    # Remove markdown code blocks if present
    if response_text.startswith("```json"):
        response_text = response_text[7:]  # Remove ```json
    if response_text.startswith("```"):
        response_text = response_text[3:]  # Remove ```
    if response_text.endswith("```"):
        response_text = response_text[:-3]  # Remove trailing ```

    response_text = response_text.strip()

    # Find first { and last }
    start_idx = response_text.find("{")
    end_idx = response_text.rfind("}")

    if start_idx == -1 or end_idx == -1:
        raise ValueError("No JSON object found in response")

    json_text = response_text[start_idx : end_idx + 1]

    try:
        return json.loads(json_text)
    except json.JSONDecodeError as e:
        logging.error("Failed to parse JSON: %s", e)
        logging.error("Response text: %s", json_text[:500])
        raise ValueError(f"Invalid JSON in LLM response: {e}")


def create_mock_snapshot() -> Dict[str, Any]:
    """Create a mock market snapshot for testing without API calls.

    Returns:
        Mock snapshot dictionary with realistic test data
    """
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


def validate_llm_output(llm_output: Dict[str, Any]) -> None:
    """Validate LLM output structure and values.

    Args:
        llm_output: Parsed LLM response

    Raises:
        ValueError: If output is invalid
    """
    required_fields = [
        "prob_bull",
        "prob_bear",
        "regime_label",
        "confidence_level",
        "scores",
    ]

    for field in required_fields:
        if field not in llm_output:
            raise ValueError(f"Missing required field: {field}")

    # Validate probabilities
    prob_bull = llm_output["prob_bull"]
    prob_bear = llm_output["prob_bear"]

    if not (0.0 <= prob_bull <= 1.0):
        raise ValueError(f"Invalid prob_bull: {prob_bull}")
    if not (0.0 <= prob_bear <= 1.0):
        raise ValueError(f"Invalid prob_bear: {prob_bear}")

    prob_sum = prob_bull + prob_bear
    if abs(prob_sum - 1.0) > 0.05:  # Allow 5% tolerance
        logging.warning(f"Probabilities sum to {prob_sum}, expected 1.0")

    # Validate scores
    scores = llm_output["scores"]
    required_scores = [
        "global_sentiment",
        "btc_sentiment",
        "onchain_pressure",
        "liquidity_risk",
        "news_risk",
        "trend_strength",
    ]

    for score_name in required_scores:
        if score_name not in scores:
            logging.warning(f"Missing score: {score_name}")


def run_full_cycle_test(
    use_real_data: bool = False,
    ollama_model: str = "deepseek-v3.1:671b-cloud",
    ollama_url: str = "http://localhost:11434",
) -> None:
    """Run complete trading system test from data collection to position sizing.

    Args:
        use_real_data: If True, fetch real market data; if False, use mock data
        ollama_model: Ollama model name to use
        ollama_url: Ollama API base URL
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

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
    # STEP 2: Build Prompts
    # =========================================================================
    print("[STEP 2] Building prompts for LLM...")
    print("-" * 80)

    system_prompt = build_system_prompt()
    user_prompt = build_user_prompt(snapshot, horizon_hours, base_asset)

    print(f"✓ System prompt length: {len(system_prompt)} chars")
    print(f"✓ User prompt length: {len(user_prompt)} chars")
    print()

    # =========================================================================
    # STEP 3: Send Request to LLM
    # =========================================================================
    print("[STEP 3] Sending request to LLM...")
    print("-" * 80)
    print(f"Model: {ollama_model}")
    print(f"Endpoint: {ollama_url}")

    try:
        # Create provider and client
        provider = OllamaProvider(
            base_url=ollama_url,
            model=ollama_model,
            timeout=180,  # 3 minutes timeout for large models
        )

        retry_policy = RetryPolicy(max_retries=2, base_delay=2.0)
        client = LLMClientSync(provider=provider, retry_policy=retry_policy)

        # Make request
        print("Waiting for LLM response (this may take 10-60 seconds)...")
        response_text = client.complete(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.1,  # Low temperature for more deterministic output
        )

        print("✓ Received response from LLM")
        print(f"  Response length: {len(response_text)} chars")
        print()

    except Exception as e:
        print(f"✗ LLM request failed: {e}")
        print()
        print("Possible issues:")
        print("1. Ollama service not running (run: ollama serve)")
        print(f"2. Model '{ollama_model}' not available (run: ollama pull {ollama_model})")
        print("3. Timeout (try smaller model or increase timeout)")
        sys.exit(1)

    # =========================================================================
    # STEP 4: Parse LLM Response
    # =========================================================================
    print("[STEP 4] Parsing LLM response...")
    print("-" * 80)

    try:
        llm_output = parse_llm_response(response_text)
        validate_llm_output(llm_output)

        print("✓ Successfully parsed JSON response")
        print(f"  Regime: {llm_output.get('regime_label', 'N/A')}")
        print(f"  Confidence: {llm_output.get('confidence_level', 'N/A')}")
        print(f"  Bull probability: {llm_output.get('prob_bull', 0):.2%}")
        print(f"  Bear probability: {llm_output.get('prob_bear', 0):.2%}")
        print()

    except ValueError as e:
        print(f"✗ Failed to parse LLM response: {e}")
        print()
        print("Raw response (first 500 chars):")
        print(response_text[:500])
        sys.exit(1)

    # =========================================================================
    # STEP 5: Calculate Position Sizing
    # =========================================================================
    print("[STEP 5] Calculating position sizing...")
    print("-" * 80)

    base_size = 0.01  # 1% of capital

    try:
        pos_long, k_long, k_short = compute_position_multipliers(
            llm_output=llm_output,
            side="long",
            base_long_size=base_size,
            base_short_size=base_size,
            k_max=2.0,
        )

        pos_short, _, _ = compute_position_multipliers(
            llm_output=llm_output,
            side="short",
            base_long_size=base_size,
            base_short_size=base_size,
            k_max=2.0,
        )

        print("✓ Position sizing calculated")
        print(f"  Long multiplier (k_long):  {k_long:.4f}")
        print(f"  Short multiplier (k_short): {k_short:.4f}")
        print(f"  Long position size:  {pos_long:.6f} ({pos_long * 100:.2f}% capital)")
        print(f"  Short position size: {pos_short:.6f} ({pos_short * 100:.2f}% capital)")
        print()

    except Exception as e:
        print(f"✗ Position sizing failed: {e}")
        sys.exit(1)

    # =========================================================================
    # STEP 6: Display Final Results
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
    print(f"  Base size:          {base_size * 100:.1f}% capital")
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
        for i, factor in enumerate(factors, 1):
            print(f"  {i}. {factor}")
        print()

    # Trading recommendation
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
    """Main entry point."""
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
