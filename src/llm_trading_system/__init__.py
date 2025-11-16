"""LLM Trading System - A regime-based trading system using LLM analysis.

This package provides a modular trading system that combines:
- Market data aggregation and analysis
- LLM-based regime classification
- Position sizing based on regime and risk metrics
"""

__version__ = "0.1.0"

# Submodules are imported lazily when accessed
# This avoids circular imports and keeps the package lightweight
__all__ = [
    "core",
    "infra",
    "cli",
]
