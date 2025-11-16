"""LLM Trading System - A regime-based trading system using LLM analysis.

This package provides a modular trading system that combines:
- Market data aggregation and analysis
- LLM-based regime classification
- Position sizing based on regime and risk metrics
"""

__version__ = "0.1.0"

# Re-export key modules for convenience
from .core import market_snapshot, position_sizing, regime_engine  # noqa: E402,F401

__all__ = [
    "core",
    "infra",
    "cli",
    "market_snapshot",
    "position_sizing",
    "regime_engine",
]
