"""Unit tests for the position sizing module."""

from __future__ import annotations

import unittest
from typing import Any

from position_sizing import clamp, compute_position_multipliers, safe_get_score


class TestHelperFunctions(unittest.TestCase):
    """Test helper functions."""

    def test_clamp_basic(self) -> None:
        """Test basic clamp functionality."""
        self.assertEqual(clamp(0.5, 0.0, 1.0), 0.5)
        self.assertEqual(clamp(-0.5, 0.0, 1.0), 0.0)
        self.assertEqual(clamp(1.5, 0.0, 1.0), 1.0)
        self.assertEqual(clamp(5.0, 2.0, 10.0), 5.0)
        self.assertEqual(clamp(1.0, 2.0, 10.0), 2.0)
        self.assertEqual(clamp(15.0, 2.0, 10.0), 10.0)

    def test_safe_get_score_basic(self) -> None:
        """Test safe score retrieval."""
        scores = {"sentiment": 0.5, "risk": 0.3}
        self.assertEqual(safe_get_score(scores, "sentiment", 0.0), 0.5)
        self.assertEqual(safe_get_score(scores, "risk", 0.0), 0.3)
        self.assertEqual(safe_get_score(scores, "missing", 0.0), 0.0)
        self.assertEqual(safe_get_score(scores, "missing", 0.5), 0.5)

    def test_safe_get_score_none_value(self) -> None:
        """Test safe score retrieval with None values."""
        scores = {"sentiment": None}
        self.assertEqual(safe_get_score(scores, "sentiment", 0.0), 0.0)

    def test_safe_get_score_invalid_type(self) -> None:
        """Test safe score retrieval with invalid types."""
        scores: dict[str, Any] = {"sentiment": "invalid"}
        # Should return default on conversion error
        self.assertEqual(safe_get_score(scores, "sentiment", 0.0), 0.0)


class TestPositionMultipliers(unittest.TestCase):
    """Test position multiplier computation."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.base_llm_output = {
            "prob_bull": 0.5,
            "prob_bear": 0.5,
            "scores": {
                "global_sentiment": 0.0,
                "btc_sentiment": 0.0,
                "altcoin_sentiment": 0.0,
                "onchain_pressure": 0.0,
                "liquidity_risk": 0.0,
                "news_risk": 0.0,
                "trend_strength": 0.0,
            },
        }

    def test_invalid_side(self) -> None:
        """Test that invalid side raises ValueError."""
        with self.assertRaises(ValueError):
            compute_position_multipliers(
                self.base_llm_output,
                side="invalid",
                base_long_size=0.01,
                base_short_size=0.01,
            )

    def test_neutral_regime_zero_scores(self) -> None:
        """Test neutral regime with all zero scores."""
        pos_size, k_long, k_short = compute_position_multipliers(
            self.base_llm_output,
            side="long",
            base_long_size=0.01,
            base_short_size=0.01,
        )
        # With prob_bull = prob_bear = 0.5 and all scores = 0, both multipliers should be ~1.0
        # But note the dead zone (d0=0.1) means d_eff = 0
        # So k_dir_long = k_dir_short = 1.0
        # All other factors are 1.0 (sentiment, chain, trend all neutral)
        # Risk factor = 1.0 (no risk)
        # Result: k_long = k_short = 1.0
        self.assertAlmostEqual(k_long, 1.0, places=4)
        self.assertAlmostEqual(k_short, 1.0, places=4)
        self.assertAlmostEqual(pos_size, 0.01, places=6)

    def test_bullish_regime_increases_long_decreases_short(self) -> None:
        """Test that bullish regime increases long multiplier and decreases short."""
        llm_output = self.base_llm_output.copy()
        llm_output["prob_bull"] = 0.7
        llm_output["prob_bear"] = 0.3

        pos_long, k_long, k_short = compute_position_multipliers(
            llm_output,
            side="long",
            base_long_size=0.01,
            base_short_size=0.01,
        )

        # In bullish regime: k_long > 1.0, k_short < 1.0
        self.assertGreater(k_long, 1.0)
        self.assertLess(k_short, 1.0)

    def test_bearish_regime_increases_short_decreases_long(self) -> None:
        """Test that bearish regime increases short multiplier and decreases long."""
        llm_output = self.base_llm_output.copy()
        llm_output["prob_bull"] = 0.3
        llm_output["prob_bear"] = 0.7

        pos_short, k_long, k_short = compute_position_multipliers(
            llm_output,
            side="short",
            base_long_size=0.01,
            base_short_size=0.01,
        )

        # In bearish regime: k_short > 1.0, k_long < 1.0
        self.assertGreater(k_short, 1.0)
        self.assertLess(k_long, 1.0)

    def test_positive_sentiment_boosts_longs(self) -> None:
        """Test that positive sentiment boosts long positions."""
        llm_output_neutral = self.base_llm_output.copy()
        llm_output_neutral["scores"] = llm_output_neutral["scores"].copy()

        llm_output_positive = self.base_llm_output.copy()
        llm_output_positive["scores"] = llm_output_positive["scores"].copy()
        llm_output_positive["scores"]["btc_sentiment"] = 0.8

        _, k_long_neutral, _ = compute_position_multipliers(
            llm_output_neutral,
            side="long",
            base_long_size=0.01,
            base_short_size=0.01,
        )

        _, k_long_positive, _ = compute_position_multipliers(
            llm_output_positive,
            side="long",
            base_long_size=0.01,
            base_short_size=0.01,
        )

        # Positive sentiment should increase long multiplier
        self.assertGreater(k_long_positive, k_long_neutral)

    def test_negative_sentiment_boosts_shorts(self) -> None:
        """Test that negative sentiment boosts short positions."""
        llm_output_neutral = self.base_llm_output.copy()
        llm_output_neutral["scores"] = llm_output_neutral["scores"].copy()

        llm_output_negative = self.base_llm_output.copy()
        llm_output_negative["scores"] = llm_output_negative["scores"].copy()
        llm_output_negative["scores"]["btc_sentiment"] = -0.8

        _, _, k_short_neutral = compute_position_multipliers(
            llm_output_neutral,
            side="short",
            base_long_size=0.01,
            base_short_size=0.01,
        )

        _, _, k_short_negative = compute_position_multipliers(
            llm_output_negative,
            side="short",
            base_long_size=0.01,
            base_short_size=0.01,
        )

        # Negative sentiment should increase short multiplier
        self.assertGreater(k_short_negative, k_short_neutral)

    def test_high_risk_throttles_positions(self) -> None:
        """Test that high risk reduces both multipliers."""
        llm_output_low_risk = self.base_llm_output.copy()
        llm_output_low_risk["scores"] = llm_output_low_risk["scores"].copy()
        llm_output_low_risk["scores"]["liquidity_risk"] = 0.1
        llm_output_low_risk["scores"]["news_risk"] = 0.1

        llm_output_high_risk = self.base_llm_output.copy()
        llm_output_high_risk["scores"] = llm_output_high_risk["scores"].copy()
        llm_output_high_risk["scores"]["liquidity_risk"] = 0.7
        llm_output_high_risk["scores"]["news_risk"] = 0.6

        _, k_long_low, k_short_low = compute_position_multipliers(
            llm_output_low_risk,
            side="long",
            base_long_size=0.01,
            base_short_size=0.01,
        )

        _, k_long_high, k_short_high = compute_position_multipliers(
            llm_output_high_risk,
            side="long",
            base_long_size=0.01,
            base_short_size=0.01,
        )

        # High risk should reduce both multipliers
        self.assertLess(k_long_high, k_long_low)
        self.assertLess(k_short_high, k_short_low)

    def test_extreme_risk_disables_trading(self) -> None:
        """Test that extreme risk (>0.9) disables all trading."""
        llm_output = self.base_llm_output.copy()
        llm_output["scores"] = llm_output["scores"].copy()
        llm_output["scores"]["news_risk"] = 0.95

        pos_size, k_long, k_short = compute_position_multipliers(
            llm_output,
            side="long",
            base_long_size=0.01,
            base_short_size=0.01,
        )

        # All multipliers and position size should be 0
        self.assertEqual(k_long, 0.0)
        self.assertEqual(k_short, 0.0)
        self.assertEqual(pos_size, 0.0)

    def test_k_max_bounds_multipliers(self) -> None:
        """Test that multipliers are bounded by k_max."""
        # Create extreme bullish scenario
        llm_output = self.base_llm_output.copy()
        llm_output["prob_bull"] = 1.0
        llm_output["prob_bear"] = 0.0
        llm_output["scores"] = llm_output["scores"].copy()
        llm_output["scores"]["btc_sentiment"] = 1.0
        llm_output["scores"]["onchain_pressure"] = 1.0
        llm_output["scores"]["trend_strength"] = 1.0

        k_max = 2.0
        _, k_long, k_short = compute_position_multipliers(
            llm_output,
            side="long",
            base_long_size=0.01,
            base_short_size=0.01,
            k_max=k_max,
        )

        # Multipliers should not exceed k_max
        self.assertLessEqual(k_long, k_max)
        self.assertLessEqual(k_short, k_max)

    def test_probability_normalization(self) -> None:
        """Test that invalid probabilities are normalized."""
        llm_output = self.base_llm_output.copy()
        llm_output["prob_bull"] = 0.6
        llm_output["prob_bear"] = 0.6  # Invalid: sum > 1

        # Should not raise, should normalize
        pos_size, k_long, k_short = compute_position_multipliers(
            llm_output,
            side="long",
            base_long_size=0.01,
            base_short_size=0.01,
        )

        # Should return valid results
        self.assertIsInstance(pos_size, float)
        self.assertIsInstance(k_long, float)
        self.assertIsInstance(k_short, float)
        self.assertGreaterEqual(k_long, 0.0)
        self.assertGreaterEqual(k_short, 0.0)

    def test_missing_scores_handled_gracefully(self) -> None:
        """Test that missing scores are handled with defaults."""
        llm_output = {
            "prob_bull": 0.6,
            "prob_bear": 0.4,
            "scores": {},  # Empty scores
        }

        # Should not raise, should use defaults
        pos_size, k_long, k_short = compute_position_multipliers(
            llm_output,
            side="long",
            base_long_size=0.01,
            base_short_size=0.01,
        )

        self.assertIsInstance(pos_size, float)
        self.assertGreaterEqual(k_long, 0.0)
        self.assertGreaterEqual(k_short, 0.0)

    def test_position_size_calculation_long(self) -> None:
        """Test position size calculation for long side."""
        llm_output = self.base_llm_output.copy()
        llm_output["prob_bull"] = 0.7
        llm_output["prob_bear"] = 0.3

        base_long_size = 0.02
        pos_size, k_long, _ = compute_position_multipliers(
            llm_output,
            side="long",
            base_long_size=base_long_size,
            base_short_size=0.01,
        )

        # Position size should equal base_long_size * k_long
        expected_pos_size = base_long_size * k_long
        self.assertAlmostEqual(pos_size, expected_pos_size, places=10)

    def test_position_size_calculation_short(self) -> None:
        """Test position size calculation for short side."""
        llm_output = self.base_llm_output.copy()
        llm_output["prob_bull"] = 0.3
        llm_output["prob_bear"] = 0.7

        base_short_size = 0.015
        pos_size, _, k_short = compute_position_multipliers(
            llm_output,
            side="short",
            base_long_size=0.01,
            base_short_size=base_short_size,
        )

        # Position size should equal base_short_size * k_short
        expected_pos_size = base_short_size * k_short
        self.assertAlmostEqual(pos_size, expected_pos_size, places=10)

    def test_trend_strength_amplifies_directional_bias(self) -> None:
        """Test that high trend strength amplifies the directional bias."""
        llm_output_weak_trend = self.base_llm_output.copy()
        llm_output_weak_trend["prob_bull"] = 0.7
        llm_output_weak_trend["prob_bear"] = 0.3
        llm_output_weak_trend["scores"] = llm_output_weak_trend["scores"].copy()
        llm_output_weak_trend["scores"]["trend_strength"] = 0.1

        llm_output_strong_trend = self.base_llm_output.copy()
        llm_output_strong_trend["prob_bull"] = 0.7
        llm_output_strong_trend["prob_bear"] = 0.3
        llm_output_strong_trend["scores"] = llm_output_strong_trend["scores"].copy()
        llm_output_strong_trend["scores"]["trend_strength"] = 0.9

        _, k_long_weak, _ = compute_position_multipliers(
            llm_output_weak_trend,
            side="long",
            base_long_size=0.01,
            base_short_size=0.01,
        )

        _, k_long_strong, _ = compute_position_multipliers(
            llm_output_strong_trend,
            side="long",
            base_long_size=0.01,
            base_short_size=0.01,
        )

        # Strong trend should increase long multiplier more
        self.assertGreater(k_long_strong, k_long_weak)

    def test_onchain_pressure_affects_multipliers(self) -> None:
        """Test that on-chain pressure affects multipliers appropriately."""
        llm_output_positive = self.base_llm_output.copy()
        llm_output_positive["scores"] = llm_output_positive["scores"].copy()
        llm_output_positive["scores"]["onchain_pressure"] = 0.5

        llm_output_negative = self.base_llm_output.copy()
        llm_output_negative["scores"] = llm_output_negative["scores"].copy()
        llm_output_negative["scores"]["onchain_pressure"] = -0.5

        _, k_long_pos, k_short_pos = compute_position_multipliers(
            llm_output_positive,
            side="long",
            base_long_size=0.01,
            base_short_size=0.01,
        )

        _, k_long_neg, k_short_neg = compute_position_multipliers(
            llm_output_negative,
            side="long",
            base_long_size=0.01,
            base_short_size=0.01,
        )

        # Positive on-chain pressure should boost longs more than negative
        self.assertGreater(k_long_pos, k_long_neg)
        # Negative on-chain pressure should boost shorts more than positive
        self.assertGreater(k_short_neg, k_short_pos)


if __name__ == "__main__":
    unittest.main()
