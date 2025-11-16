"""Core trading system logic.

This module contains the core business logic for the trading system:
- market_snapshot: Market data aggregation and prompt preparation
- position_sizing: Convert regime assessments to position multipliers
- regime_engine: End-to-end pipeline orchestration
"""

# Submodules can be imported individually as needed
# e.g., from llm_trading_system.core import market_snapshot
# or from llm_trading_system.core.position_sizing import compute_position_multipliers

__all__ = [
    "market_snapshot",
    "position_sizing",
    "regime_engine",
]
