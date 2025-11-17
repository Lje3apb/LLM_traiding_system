"""File-based storage for strategy configurations."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


# Default storage directory (relative to project root)
DEFAULT_STORAGE_DIR = Path(__file__).resolve().parent.parent.parent / "strategies_configs"


def _sanitize_name(name: str) -> str:
    """Sanitize config name to ensure it's a safe filename.

    Args:
        name: Config name to sanitize

    Returns:
        Sanitized name (alphanumeric + underscore/dash only)

    Raises:
        ValueError: If name is empty or invalid after sanitization
    """
    # Only allow alphanumeric, underscore, and dash
    sanitized = re.sub(r'[^a-zA-Z0-9_-]', '', name)
    if not sanitized:
        raise ValueError(f"Invalid config name: {name}")
    return sanitized


def list_configs(storage_dir: Path | None = None) -> list[str]:
    """List all available strategy configuration names.

    Args:
        storage_dir: Directory where configs are stored (default: DEFAULT_STORAGE_DIR)

    Returns:
        List of config names (without .json extension)
    """
    if storage_dir is None:
        storage_dir = DEFAULT_STORAGE_DIR

    # Create directory if it doesn't exist
    storage_dir.mkdir(parents=True, exist_ok=True)

    # List all .json files
    config_files = storage_dir.glob("*.json")
    return [f.stem for f in config_files]


def load_config(name: str, storage_dir: Path | None = None) -> dict[str, Any]:
    """Load a strategy configuration by name.

    Args:
        name: Config name (without .json extension)
        storage_dir: Directory where configs are stored (default: DEFAULT_STORAGE_DIR)

    Returns:
        Configuration dictionary

    Raises:
        FileNotFoundError: If config doesn't exist
        json.JSONDecodeError: If config file contains invalid JSON
        ValueError: If name is invalid
    """
    if storage_dir is None:
        storage_dir = DEFAULT_STORAGE_DIR

    # Sanitize name
    safe_name = _sanitize_name(name)

    # Build path
    config_path = storage_dir / f"{safe_name}.json"

    if not config_path.exists():
        raise FileNotFoundError(f"Config '{name}' not found at {config_path}")

    # Load and return
    with config_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_config(name: str, config: dict[str, Any], storage_dir: Path | None = None) -> None:
    """Save a strategy configuration.

    Args:
        name: Config name (without .json extension)
        config: Configuration dictionary to save
        storage_dir: Directory where configs are stored (default: DEFAULT_STORAGE_DIR)

    Raises:
        ValueError: If name is invalid
    """
    if storage_dir is None:
        storage_dir = DEFAULT_STORAGE_DIR

    # Sanitize name
    safe_name = _sanitize_name(name)

    # Create directory if it doesn't exist
    storage_dir.mkdir(parents=True, exist_ok=True)

    # Build path
    config_path = storage_dir / f"{safe_name}.json"

    # Save config
    with config_path.open("w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


def delete_config(name: str, storage_dir: Path | None = None) -> None:
    """Delete a strategy configuration.

    Args:
        name: Config name (without .json extension)
        storage_dir: Directory where configs are stored (default: DEFAULT_STORAGE_DIR)

    Raises:
        FileNotFoundError: If config doesn't exist
        ValueError: If name is invalid
    """
    if storage_dir is None:
        storage_dir = DEFAULT_STORAGE_DIR

    # Sanitize name
    safe_name = _sanitize_name(name)

    # Build path
    config_path = storage_dir / f"{safe_name}.json"

    if not config_path.exists():
        raise FileNotFoundError(f"Config '{name}' not found at {config_path}")

    # Delete file
    config_path.unlink()


__all__ = ["list_configs", "load_config", "save_config", "delete_config"]
