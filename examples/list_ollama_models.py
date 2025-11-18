#!/usr/bin/env python3
"""Example script to list available Ollama models."""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from llm_trading_system.infra.llm_infra import list_ollama_models
from llm_trading_system.config import load_config


def main():
    """List all available Ollama models."""
    print("=" * 80)
    print("Ollama Models List")
    print("=" * 80)
    print()

    # Load config to get Ollama URL
    cfg = load_config()
    base_url = cfg.llm.ollama_base_url

    print(f"Fetching models from: {base_url}")
    print()

    # Fetch models
    models = list_ollama_models(base_url)

    if not models:
        print("⚠️  No models found or Ollama server is not accessible.")
        print()
        print("Make sure:")
        print("1. Ollama is running (run: ollama serve)")
        print("2. The URL is correct in your config")
        print(f"   Current URL: {base_url}")
        return

    print(f"✓ Found {len(models)} model(s):")
    print()

    for i, model in enumerate(models, start=1):
        print(f"  {i}. {model}")

    print()
    print("=" * 80)
    print()
    print("To use a model in your config:")
    print()
    print("  1. Edit ~/.llm_trading/config.json")
    print('  2. Set "default_model" to one of the models above')
    print()
    print("Example:")
    print('  "llm": {')
    print('    "llm_provider": "ollama",')
    print(f'    "default_model": "{models[0] if models else "llama3.2"}",')
    print('    ...')
    print('  }')
    print()


if __name__ == "__main__":
    main()
