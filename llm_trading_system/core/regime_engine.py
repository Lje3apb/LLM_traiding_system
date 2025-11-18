"""Core regime evaluation pipeline combining LLM reasoning and position sizing."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from llm_trading_system.core.market_snapshot import build_system_prompt, build_user_prompt
from llm_trading_system.core.position_sizing import compute_position_multipliers


def parse_llm_response(response_text: str) -> Dict[str, Any]:
    """Parse LLM JSON response with error handling."""
    response_text = response_text.strip()

    if response_text.startswith("```json"):
        response_text = response_text[7:]
    if response_text.startswith("```"):
        response_text = response_text[3:]
    if response_text.endswith("```"):
        response_text = response_text[:-3]

    response_text = response_text.strip()

    start_idx = response_text.find("{")
    end_idx = response_text.rfind("}")

    if start_idx == -1 or end_idx == -1:
        raise ValueError("No JSON object found in response")

    json_text = response_text[start_idx : end_idx + 1]

    try:
        return json.loads(json_text)
    except json.JSONDecodeError as exc:
        logging.error("Failed to parse JSON: %s", exc)
        logging.error("Response text: %s", json_text[:500])
        raise ValueError(f"Invalid JSON in LLM response: {exc}") from exc


def validate_llm_output(llm_output: Dict[str, Any]) -> None:
    """Validate LLM output structure and values."""
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

    prob_bull = llm_output["prob_bull"]
    prob_bear = llm_output["prob_bear"]

    if not (0.0 <= prob_bull <= 1.0):
        raise ValueError(f"Invalid prob_bull: {prob_bull}")
    if not (0.0 <= prob_bear <= 1.0):
        raise ValueError(f"Invalid prob_bear: {prob_bear}")

    prob_sum = prob_bull + prob_bear
    if abs(prob_sum - 1.0) > 0.05:
        logging.warning("Probabilities sum to %s, expected 1.0", prob_sum)

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
            logging.warning("Missing score: %s", score_name)


def evaluate_regime_and_size(
    snapshot: dict,
    client: Any,
    base_size: float = 0.01,
    k_max: float = 2.0,
    temperature: float = 0.1,
) -> dict:
    """Run the full LLM + sizing pipeline and return consolidated results.

    Args:
        snapshot: Market snapshot data dictionary
        client: LLM client with complete() method
        base_size: Base position size (default: 0.01)
        k_max: Maximum position multiplier (default: 2.0)
        temperature: LLM sampling temperature (default: 0.1)

    Returns:
        dict: Consolidated results with regime analysis and position sizing
    """

    system_prompt = build_system_prompt()
    user_prompt = build_user_prompt(
        snapshot,
        snapshot["horizon_hours"],
        snapshot["base_asset"],
    )

    response_text = client.complete(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=temperature,
    )

    llm_output = parse_llm_response(response_text)
    validate_llm_output(llm_output)

    pos_long, k_long, k_short = compute_position_multipliers(
        llm_output=llm_output,
        side="long",
        base_long_size=base_size,
        base_short_size=base_size,
        k_max=k_max,
    )

    pos_short, _, _ = compute_position_multipliers(
        llm_output=llm_output,
        side="short",
        base_long_size=base_size,
        base_short_size=base_size,
        k_max=k_max,
    )

    return {
        "llm_output": llm_output,
        "k_long": k_long,
        "k_short": k_short,
        "pos_long": pos_long,
        "pos_short": pos_short,
    }
