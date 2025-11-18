"""Position sizing module for converting LLM regime output to position multipliers.

This module converts probabilistic regime assessments and market scores from an LLM
into concrete position size multipliers (k_long and k_short) that can be applied to
base position sizes.

The sizing logic follows a regime-based approach that combines:
1. Directional bias from probability estimates (prob_bull vs prob_bear)
2. Score-based adjustments (sentiment, on-chain metrics, trend strength)
3. Risk throttling based on liquidity and news risk

This is purely a sizing layer - it does NOT generate trading signals.
"""

from __future__ import annotations

import logging
from typing import Any


def clamp(x: float, lo: float, hi: float) -> float:
    """Clamp value x to the range [lo, hi].

    Args:
        x: Value to clamp
        lo: Lower bound
        hi: Upper bound

    Returns:
        Clamped value in [lo, hi]
    """
    return max(lo, min(hi, x))


def safe_get_score(scores: dict[str, Any], key: str, default: float = 0.0) -> float:
    """Safely retrieve a score from the scores dict, with fallback to default.

    Args:
        scores: Dictionary of scores
        key: Score key to retrieve
        default: Default value if key is missing or invalid

    Returns:
        Score value as float, or default if not available
    """
    try:
        value = scores.get(key, default)
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        logging.warning("Invalid score value for key '%s', using default %.2f", key, default)
        return default


def compute_position_multipliers(
    llm_output: dict[str, Any],
    side: str,
    base_long_size: float,
    base_short_size: float,
    *,
    k_max: float = 2.0,
) -> tuple[float, float, float]:
    """Convert LLM regime output into position size multipliers using aggressive non-linear sizing.

    This function implements an aggressive regime-based position sizing strategy that amplifies
    directional edge through non-linear transformations while maintaining risk controls. The new
    approach uses:
    - Non-linear edge amplification (power function with gamma < 1)
    - Confidence-based scaling
    - Trend-strength alignment
    - Risk throttling based on liquidity and news risk

    Args:
        llm_output: Dictionary containing:
            - prob_bull (float): Probability of bull regime, in [0, 1]
            - prob_bear (float): Probability of bear regime, in [0, 1]
            - confidence_level (str): "low", "medium", or "high"
            - scores (dict): Dictionary of market scores:
                - trend_strength (float): 0 to 1 (0 = no trend, 1 = strong)
                - liquidity_risk (float): 0 to 1 (higher = more dangerous)
                - news_risk (float): 0 to 1 (higher = more dangerous)
        side: "long" or "short" - the side for which to compute position size
        base_long_size: Base position size for long entries (e.g., 0.01 = 1% of equity)
        base_short_size: Base position size for short entries
        k_max: Maximum multiplier value (default 2.0)

    Returns:
        Tuple of (position_size, k_long, k_short):
            - position_size: Final position size for this trade given the side
            - k_long: Current long multiplier (for logging/monitoring)
            - k_short: Current short multiplier (for logging/monitoring)

    Raises:
        ValueError: If side is not "long" or "short"

    Example:
        >>> llm_output = {
        ...     "prob_bull": 0.75,
        ...     "prob_bear": 0.25,
        ...     "confidence_level": "high",
        ...     "scores": {
        ...         "trend_strength": 0.7,
        ...         "liquidity_risk": 0.2,
        ...         "news_risk": 0.1,
        ...     }
        ... }
        >>> pos_size, k_long, k_short = compute_position_multipliers(
        ...     llm_output, "long", 0.01, 0.01, k_max=2.0
        ... )
        >>> print(f"Long multiplier: {k_long:.2f}, Short multiplier: {k_short:.2f}")
    """
    # Validate side parameter
    if side not in ("long", "short"):
        raise ValueError(f"side must be 'long' or 'short', got '{side}'")

    # ========================================================================
    # HYPERPARAMETERS (tuned for aggressive but controlled sizing)
    # ========================================================================
    EDGE_GAIN = 2.5  # Amplifies edge (higher = more aggressive)
    EDGE_GAMMA = 0.7  # Non-linear compression exponent (< 1 for diminishing returns)
    BASE_K = 0.5  # Neutral multiplier baseline

    # ========================================================================
    # 1. EXTRACT AND VALIDATE PROBABILITIES
    # ========================================================================
    prob_bull = llm_output.get("prob_bull", 0.5)
    prob_bear = llm_output.get("prob_bear", 0.5)

    # Validate and normalize probabilities
    if not (0.0 <= prob_bull <= 1.0 and 0.0 <= prob_bear <= 1.0):
        logging.warning(
            "Probabilities out of range: prob_bull=%.3f, prob_bear=%.3f. Clamping to [0, 1].",
            prob_bull,
            prob_bear,
        )
        prob_bull = clamp(prob_bull, 0.0, 1.0)
        prob_bear = clamp(prob_bear, 0.0, 1.0)

    # Normalize probabilities to sum to 1.0
    prob_sum = prob_bull + prob_bear
    if abs(prob_sum - 1.0) > 0.01:
        logging.warning(
            "Probabilities sum to %.3f (not 1.0). Normalizing: prob_bull=%.3f, prob_bear=%.3f",
            prob_sum,
            prob_bull,
            prob_bear,
        )
        if prob_sum > 0:
            prob_bull = prob_bull / prob_sum
            prob_bear = prob_bear / prob_sum
        else:
            prob_bull = 0.5
            prob_bear = 0.5

    # ========================================================================
    # 2. EXTRACT CONFIDENCE AND SCORES
    # ========================================================================
    confidence_level = llm_output.get("confidence_level", "low")
    scores = llm_output.get("scores", {})

    trend_strength = clamp(safe_get_score(scores, "trend_strength", 0.0), 0.0, 1.0)
    liquidity_risk = clamp(safe_get_score(scores, "liquidity_risk", 0.0), 0.0, 1.0)
    news_risk = clamp(safe_get_score(scores, "news_risk", 0.0), 0.0, 1.0)

    # ========================================================================
    # 3. COMPUTE EDGE (directional bias from probabilities)
    # ========================================================================
    # edge > 0 means bullish, edge < 0 means bearish
    edge = prob_bull - 0.5
    edge_abs = abs(edge)

    # ========================================================================
    # 4. APPLY CONFIDENCE SCALING
    # ========================================================================
    if confidence_level == "low":
        conf_scale = 0.7
    elif confidence_level == "high":
        conf_scale = 1.3
    else:  # "medium" or unknown
        conf_scale = 1.0

    # ========================================================================
    # 5. APPLY TREND SCALING
    # ========================================================================
    # Boost multiplier when trend aligns with edge
    # Range: 0.8 (weak trend) to 1.2 (strong trend)
    trend_scale = 0.8 + 0.4 * trend_strength

    # ========================================================================
    # 6. COMPUTE EFFECTIVE EDGE (non-linear amplification)
    # ========================================================================
    # Amplify edge and apply power compression
    edge_eff = edge_abs * EDGE_GAIN
    edge_eff = edge_eff ** EDGE_GAMMA  # Non-linear compression
    edge_eff = edge_eff * conf_scale * trend_scale

    # Clamp effective edge to reasonable bounds
    edge_eff = clamp(edge_eff, 0.0, 0.9)

    # ========================================================================
    # 7. COMPUTE BASE MULTIPLIERS
    # ========================================================================
    if edge >= 0:  # Bullish bias
        k_long = BASE_K + edge_eff
        k_short = BASE_K - edge_eff
    else:  # Bearish bias
        k_long = BASE_K - edge_eff
        k_short = BASE_K + edge_eff

    # ========================================================================
    # 8. APPLY RISK PENALTY
    # ========================================================================
    # Combine liquidity risk and news risk
    risk_factor = 0.5 * (liquidity_risk + news_risk)
    risk_scale = 1.0 - 0.3 * risk_factor  # Range: 1.0 (no risk) to 0.7 (high risk)
    risk_scale = clamp(risk_scale, 0.7, 1.0)

    # Apply risk penalty
    k_long = k_long * risk_scale
    k_short = k_short * risk_scale

    # Hard stop for extreme risk
    if max(liquidity_risk, news_risk) > 0.9:
        logging.warning(
            "Extremely high risk detected (liquidity_risk=%.2f, news_risk=%.2f). "
            "Disabling all new trades.",
            liquidity_risk,
            news_risk,
        )
        return 0.0, 0.0, 0.0

    # ========================================================================
    # 9. CLAMP TO [0, k_max] AND ENSURE NON-NEGATIVE
    # ========================================================================
    k_long = clamp(k_long, 0.0, k_max)
    k_short = clamp(k_short, 0.0, k_max)

    # ========================================================================
    # 10. COMPUTE FINAL POSITION SIZE FOR GIVEN SIDE
    # ========================================================================
    if side == "long":
        position_size = base_long_size * k_long
    elif side == "short":
        position_size = base_short_size * k_short
    else:
        # Should never reach here due to validation at start
        raise ValueError(f"Invalid side: {side}")

    return position_size, k_long, k_short


def main() -> None:
    """Minimal usage example demonstrating the position sizing module."""

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    # Example 1: Bullish regime with positive sentiment
    print("=" * 70)
    print("Example 1: Bullish regime (prob_bull=0.65, positive sentiment)")
    print("=" * 70)

    llm_output_bullish = {
        "prob_bull": 0.65,
        "prob_bear": 0.35,
        "scores": {
            "global_sentiment": 0.3,
            "btc_sentiment": 0.4,
            "altcoin_sentiment": 0.2,
            "onchain_pressure": 0.2,
            "liquidity_risk": 0.3,
            "news_risk": 0.2,
            "trend_strength": 0.7,
        },
    }

    pos_long, k_long, k_short = compute_position_multipliers(
        llm_output_bullish,
        side="long",
        base_long_size=0.01,
        base_short_size=0.01,
    )

    print(f"  Long multiplier (k_long):  {k_long:.4f}")
    print(f"  Short multiplier (k_short): {k_short:.4f}")
    print(f"  Position size for LONG:    {pos_long:.6f} (= 0.01 * {k_long:.4f})")
    print()

    pos_short, k_long, k_short = compute_position_multipliers(
        llm_output_bullish,
        side="short",
        base_long_size=0.01,
        base_short_size=0.01,
    )
    print(f"  Position size for SHORT:   {pos_short:.6f} (= 0.01 * {k_short:.4f})")
    print()

    # Example 2: Bearish regime with negative sentiment
    print("=" * 70)
    print("Example 2: Bearish regime (prob_bear=0.70, negative sentiment)")
    print("=" * 70)

    llm_output_bearish = {
        "prob_bull": 0.30,
        "prob_bear": 0.70,
        "scores": {
            "global_sentiment": -0.4,
            "btc_sentiment": -0.5,
            "altcoin_sentiment": -0.3,
            "onchain_pressure": -0.3,
            "liquidity_risk": 0.2,
            "news_risk": 0.15,
            "trend_strength": 0.8,
        },
    }

    pos_long, k_long, k_short = compute_position_multipliers(
        llm_output_bearish,
        side="long",
        base_long_size=0.01,
        base_short_size=0.01,
    )

    print(f"  Long multiplier (k_long):  {k_long:.4f}")
    print(f"  Short multiplier (k_short): {k_short:.4f}")
    print(f"  Position size for LONG:    {pos_long:.6f} (= 0.01 * {k_long:.4f})")
    print()

    pos_short, k_long, k_short = compute_position_multipliers(
        llm_output_bearish,
        side="short",
        base_long_size=0.01,
        base_short_size=0.01,
    )
    print(f"  Position size for SHORT:   {pos_short:.6f} (= 0.01 * {k_short:.4f})")
    print()

    # Example 3: Neutral regime (near 50/50)
    print("=" * 70)
    print("Example 3: Neutral regime (prob_bull=0.52, weak signals)")
    print("=" * 70)

    llm_output_neutral = {
        "prob_bull": 0.52,
        "prob_bear": 0.48,
        "scores": {
            "global_sentiment": 0.05,
            "btc_sentiment": 0.0,
            "altcoin_sentiment": 0.0,
            "onchain_pressure": 0.0,
            "liquidity_risk": 0.4,
            "news_risk": 0.3,
            "trend_strength": 0.2,
        },
    }

    pos_long, k_long, k_short = compute_position_multipliers(
        llm_output_neutral,
        side="long",
        base_long_size=0.01,
        base_short_size=0.01,
    )

    print(f"  Long multiplier (k_long):  {k_long:.4f}")
    print(f"  Short multiplier (k_short): {k_short:.4f}")
    print(f"  Position size for LONG:    {pos_long:.6f}")
    print(f"  Position size for SHORT:   {pos_short:.6f}")
    print()

    # Example 4: High risk environment (should throttle positions)
    print("=" * 70)
    print("Example 4: High risk environment (liquidity_risk=0.7, news_risk=0.6)")
    print("=" * 70)

    llm_output_risky = {
        "prob_bull": 0.60,
        "prob_bear": 0.40,
        "scores": {
            "global_sentiment": 0.2,
            "btc_sentiment": 0.3,
            "altcoin_sentiment": 0.1,
            "onchain_pressure": 0.1,
            "liquidity_risk": 0.7,  # High liquidity risk
            "news_risk": 0.6,  # High news risk
            "trend_strength": 0.5,
        },
    }

    pos_long, k_long, k_short = compute_position_multipliers(
        llm_output_risky,
        side="long",
        base_long_size=0.01,
        base_short_size=0.01,
    )

    print(f"  Long multiplier (k_long):  {k_long:.4f}")
    print(f"  Short multiplier (k_short): {k_short:.4f}")
    print(f"  Position size for LONG:    {pos_long:.6f}")
    print(f"  Note: Positions throttled due to high risk factors")
    print()

    # Example 5: Extreme risk - should disable trading
    print("=" * 70)
    print("Example 5: Extreme risk (news_risk=0.95) - TRADING DISABLED")
    print("=" * 70)

    llm_output_extreme = {
        "prob_bull": 0.60,
        "prob_bear": 0.40,
        "scores": {
            "global_sentiment": 0.2,
            "btc_sentiment": 0.3,
            "altcoin_sentiment": 0.1,
            "onchain_pressure": 0.1,
            "liquidity_risk": 0.3,
            "news_risk": 0.95,  # Extreme risk
            "trend_strength": 0.5,
        },
    }

    pos_long, k_long, k_short = compute_position_multipliers(
        llm_output_extreme,
        side="long",
        base_long_size=0.01,
        base_short_size=0.01,
    )

    print(f"  Long multiplier (k_long):  {k_long:.4f}")
    print(f"  Short multiplier (k_short): {k_short:.4f}")
    print(f"  Position size for LONG:    {pos_long:.6f}")
    print(f"  Note: All trading disabled due to extreme risk")
    print()


if __name__ == "__main__":
    main()
