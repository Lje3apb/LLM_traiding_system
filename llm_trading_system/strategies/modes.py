"""Strategy execution modes for the LLM trading system."""

from __future__ import annotations

from enum import Enum


class StrategyMode(str, Enum):
    """Defines the execution mode for trading strategies.

    - LLM_ONLY: Strategy uses only LLM-based regime analysis
    - QUANT_ONLY: Strategy uses only quantitative/technical indicators
    - HYBRID: Strategy combines both LLM and quantitative signals
    """

    LLM_ONLY = "llm_only"
    QUANT_ONLY = "quant_only"
    HYBRID = "hybrid"


__all__ = ["StrategyMode"]
