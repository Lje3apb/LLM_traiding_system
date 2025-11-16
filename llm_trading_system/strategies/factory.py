"""Strategy factory for creating strategies from configuration."""

from __future__ import annotations

from typing import Any

from llm_trading_system.strategies.base import Strategy
from llm_trading_system.strategies.combined_strategy import CombinedStrategy
from llm_trading_system.strategies.configs import IndicatorStrategyConfig
from llm_trading_system.strategies.indicator_strategy import IndicatorStrategy
from llm_trading_system.strategies.modes import StrategyMode
from llm_trading_system.strategies.rules import RuleSet


def create_strategy_from_config(
    cfg: dict[str, Any],
    llm_client: Any | None = None,
) -> Strategy:
    """Create a strategy instance from a configuration dictionary.

    Args:
        cfg: Configuration dictionary with keys:
            - strategy_type: "indicator" or "combined" (default: "indicator")
            - mode: "quant_only", "llm_only", or "hybrid" (from StrategyMode)
            - rules: dict with long_entry, short_entry, long_exit, short_exit
            - ... other IndicatorStrategyConfig fields
        llm_client: LLM client for combined/LLM strategies (required for non-quant modes)

    Returns:
        Strategy instance (IndicatorStrategy or CombinedStrategy)

    Raises:
        ValueError: If configuration is invalid or llm_client is missing when required
    """
    # Extract strategy type
    strategy_type = cfg.get("strategy_type", "indicator")

    # Extract rules if present
    rules_dict = cfg.get("rules")
    rules: RuleSet | None = None
    if rules_dict is not None:
        rules = RuleSet.from_dict(rules_dict)

    # Build config (exclude rules and strategy_type from indicator config)
    config_dict = {k: v for k, v in cfg.items() if k not in ("rules", "strategy_type")}
    config = IndicatorStrategyConfig.from_dict(config_dict)

    # Validate LLM requirements
    if config.mode in (StrategyMode.LLM_ONLY, StrategyMode.HYBRID):
        if llm_client is None:
            raise ValueError(
                f"llm_client is required for mode {config.mode.value}, "
                "but was not provided"
            )

    # Create strategy based on type
    if strategy_type == "indicator":
        # Pure indicator strategy (QUANT_ONLY)
        if rules is None:
            raise ValueError("rules are required for indicator strategy")
        if config.mode != StrategyMode.QUANT_ONLY:
            raise ValueError(
                f"indicator strategy_type only supports QUANT_ONLY mode, "
                f"got {config.mode.value}"
            )
        return IndicatorStrategy(config=config, rules=rules)

    elif strategy_type == "combined":
        # Combined strategy (supports all modes)
        if config.mode in (StrategyMode.QUANT_ONLY, StrategyMode.HYBRID):
            if rules is None:
                raise ValueError(
                    f"rules are required for combined strategy in {config.mode.value} mode"
                )
        return CombinedStrategy(
            config=config,
            rules=rules,
            llm_client=llm_client,
        )

    else:
        raise ValueError(
            f"Unknown strategy_type: {strategy_type}. "
            "Must be 'indicator' or 'combined'"
        )


__all__ = ["create_strategy_from_config"]
