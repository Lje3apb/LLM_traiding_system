"""Declarative rule engine for indicator-based trading strategies."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Condition:
    """A single condition for rule evaluation.

    Examples:
        {"left": "ema_fast", "op": ">", "right": "ema_slow"}
        {"left": "rsi", "op": "<", "right": 30}
        {"left": "ema_fast", "op": "cross_above", "right": "ema_slow"}
    """

    left: str
    op: str
    right: str | float | int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Condition:
        """Create Condition from dictionary.

        Args:
            data: Dictionary with "left", "op", "right" keys

        Returns:
            Condition instance
        """
        return cls(left=data["left"], op=data["op"], right=data["right"])

    def to_dict(self) -> dict[str, Any]:
        """Convert Condition to JSON-serializable dictionary.

        Returns:
            Dictionary representation
        """
        return {"left": self.left, "op": self.op, "right": self.right}


@dataclass
class RuleSet:
    """Collection of entry and exit rules for long and short positions.

    All conditions in a list are combined with AND logic.
    Empty rule lists evaluate to False (no signal).
    """

    long_entry: list[Condition] = field(default_factory=list)
    short_entry: list[Condition] = field(default_factory=list)
    long_exit: list[Condition] = field(default_factory=list)
    short_exit: list[Condition] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RuleSet:
        """Create RuleSet from dictionary.

        Args:
            data: Dictionary with keys like "long_entry", "short_entry", etc.
                  Each value is a list of condition dicts.

        Returns:
            RuleSet instance
        """
        return cls(
            long_entry=[Condition.from_dict(c) for c in data.get("long_entry", [])],
            short_entry=[Condition.from_dict(c) for c in data.get("short_entry", [])],
            long_exit=[Condition.from_dict(c) for c in data.get("long_exit", [])],
            short_exit=[Condition.from_dict(c) for c in data.get("short_exit", [])],
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert RuleSet to JSON-serializable dictionary.

        Returns:
            Dictionary with all rule conditions
        """
        return {
            "long_entry": [c.to_dict() for c in self.long_entry],
            "short_entry": [c.to_dict() for c in self.short_entry],
            "long_exit": [c.to_dict() for c in self.long_exit],
            "short_exit": [c.to_dict() for c in self.short_exit],
        }


def _evaluate_expression(
    expr: str, indicators: dict[str, float | None]
) -> float | None:
    """Evaluate a simple arithmetic expression.

    Supports expressions like:
    - "vol_ma * 1.5"
    - "vol_ma / 2"
    - "atr * 2.0"
    - "rsi - 30"
    - "rsi + -5" (negative numbers)

    IMPORTANT: Only supports single binary operations (no operator precedence).
    For complex expressions like "2 + 3 * 4", use parentheses or separate rules.

    Args:
        expr: Expression string
        indicators: Indicator values

    Returns:
        Evaluated value or None if invalid
    """
    expr = expr.strip()

    # Try multiplication (highest precedence for simple cases)
    if "*" in expr:
        parts = expr.split("*", 1)
        if len(parts) == 2:
            left = _get_value_from_str(parts[0].strip(), indicators)
            right = _get_value_from_str(parts[1].strip(), indicators)
            if left is not None and right is not None:
                return left * right

    # Try division
    if "/" in expr:
        parts = expr.split("/", 1)
        if len(parts) == 2:
            left = _get_value_from_str(parts[0].strip(), indicators)
            right = _get_value_from_str(parts[1].strip(), indicators)
            if left is not None and right is not None and right != 0:
                return left / right

    # Try addition
    if "+" in expr:
        parts = expr.split("+", 1)
        if len(parts) == 2:
            left = _get_value_from_str(parts[0].strip(), indicators)
            right = _get_value_from_str(parts[1].strip(), indicators)
            if left is not None and right is not None:
                return left + right

    # Try subtraction
    # Handle both "a - b" and "a - -b" cases
    # Find the last occurrence of '-' that's not part of a number
    minus_positions = [i for i, c in enumerate(expr) if c == '-']
    for pos in reversed(minus_positions):
        # Skip if it's at the start (negative number)
        if pos == 0:
            continue
        # Skip if previous char is an operator (e.g., "a + -5")
        if pos > 0 and expr[pos - 1] in "+-*/":
            continue

        # This '-' is a subtraction operator
        left_str = expr[:pos].strip()
        right_str = expr[pos + 1:].strip()

        left = _get_value_from_str(left_str, indicators)
        right = _get_value_from_str(right_str, indicators)
        if left is not None and right is not None:
            return left - right

    # No expression found, return simple value
    return _get_value_from_str(expr, indicators)


def _get_value_from_str(
    s: str, indicators: dict[str, float | None]
) -> float | None:
    """Get a numeric value from a string (indicator name or literal number).

    Args:
        s: String (indicator name like "rsi" or number like "30")
        indicators: Indicator values

    Returns:
        Numeric value or None
    """
    s = s.strip()

    # Try as indicator name
    if s in indicators:
        return indicators[s]

    # Try as literal number
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _evaluate_condition(
    condition: Condition,
    indicators: dict[str, float | None],
    prev_indicators: dict[str, float | None] | None = None,
) -> bool:
    """Evaluate a single condition.

    Args:
        condition: The condition to evaluate
        indicators: Current indicator values
        prev_indicators: Previous indicator values (for cross operations)

    Returns:
        True if condition is met, False otherwise
    """
    # Get left value
    left_val = indicators.get(condition.left)
    if left_val is None:
        return False

    # Get right value (supports expressions)
    if isinstance(condition.right, str):
        right_val = _evaluate_expression(condition.right, indicators)
        if right_val is None:
            return False
    else:
        right_val = condition.right

    # Handle simple comparison operators
    if condition.op == ">":
        return left_val > right_val
    elif condition.op == "<":
        return left_val < right_val
    elif condition.op == ">=":
        return left_val >= right_val
    elif condition.op == "<=":
        return left_val <= right_val
    elif condition.op == "==":
        return left_val == right_val

    # Handle cross operations (require previous values)
    elif condition.op == "cross_above":
        if prev_indicators is None:
            return False

        # Use same logic for previous values as for current values
        prev_left = prev_indicators.get(condition.left)
        if prev_left is None:
            return False

        # Support expressions for right side in previous values too
        if isinstance(condition.right, str):
            prev_right = _evaluate_expression(condition.right, prev_indicators)
            if prev_right is None:
                return False
        else:
            prev_right = condition.right

        # Cross above: was below or equal, now above
        return prev_left <= prev_right and left_val > right_val

    elif condition.op == "cross_below":
        if prev_indicators is None:
            return False

        # Use same logic for previous values as for current values
        prev_left = prev_indicators.get(condition.left)
        if prev_left is None:
            return False

        # Support expressions for right side in previous values too
        if isinstance(condition.right, str):
            prev_right = _evaluate_expression(condition.right, prev_indicators)
            if prev_right is None:
                return False
        else:
            prev_right = condition.right

        # Cross below: was above or equal, now below
        return prev_left >= prev_right and left_val < right_val

    else:
        # Unknown operator
        return False


def evaluate_rules(
    rules: RuleSet,
    indicators: dict[str, float | None],
    prev_indicators: dict[str, float | None] | None = None,
) -> dict[str, bool]:
    """Evaluate all rules in a RuleSet.

    All conditions within a rule group are combined with AND logic.
    Empty rule lists evaluate to False (no signal).

    Args:
        rules: The RuleSet to evaluate
        indicators: Current indicator values (e.g., {"ema_fast": 100.5, "rsi": 65})
        prev_indicators: Previous indicator values (required for cross operations)

    Returns:
        Dictionary with boolean results:
        {
            "long_entry": bool,
            "short_entry": bool,
            "long_exit": bool,
            "short_exit": bool
        }
    """
    result = {
        "long_entry": True,
        "short_entry": True,
        "long_exit": True,
        "short_exit": True,
    }

    # Evaluate long entry (all conditions must be True)
    for condition in rules.long_entry:
        if not _evaluate_condition(condition, indicators, prev_indicators):
            result["long_entry"] = False
            break

    # If no conditions, treat as False (no signal)
    if len(rules.long_entry) == 0:
        result["long_entry"] = False

    # Evaluate short entry
    for condition in rules.short_entry:
        if not _evaluate_condition(condition, indicators, prev_indicators):
            result["short_entry"] = False
            break

    if len(rules.short_entry) == 0:
        result["short_entry"] = False

    # Evaluate long exit
    for condition in rules.long_exit:
        if not _evaluate_condition(condition, indicators, prev_indicators):
            result["long_exit"] = False
            break

    if len(rules.long_exit) == 0:
        result["long_exit"] = False

    # Evaluate short exit
    for condition in rules.short_exit:
        if not _evaluate_condition(condition, indicators, prev_indicators):
            result["short_exit"] = False
            break

    if len(rules.short_exit) == 0:
        result["short_exit"] = False

    return result


__all__ = ["Condition", "RuleSet", "evaluate_rules"]
