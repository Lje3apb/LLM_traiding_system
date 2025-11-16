#!/usr/bin/env python3
"""Check if all dependencies are available for full cycle test."""

import sys


def check_imports():
    """Check if all required modules can be imported."""
    print("Checking Python dependencies...")
    print("-" * 60)

    required_modules = [
        ("requests", "HTTP requests"),
        ("json", "JSON parsing (built-in)"),
        ("logging", "Logging (built-in)"),
    ]

    missing = []
    for module_name, description in required_modules:
        try:
            __import__(module_name)
            print(f"✓ {module_name:20s} - {description}")
        except ImportError:
            print(f"✗ {module_name:20s} - MISSING")
            missing.append(module_name)

    print()

    # Check project modules
    print("Checking project modules...")
    print("-" * 60)

    project_modules = [
        ("llm_infra", "LLM infrastructure package"),
        ("position_sizing", "Position sizing module"),
        ("market_snapshot", "Market data collection module"),
    ]

    for module_name, description in project_modules:
        try:
            __import__(module_name)
            print(f"✓ {module_name:20s} - {description}")
        except ImportError as e:
            print(f"✗ {module_name:20s} - MISSING ({e})")
            missing.append(module_name)

    print()

    if missing:
        print(f"✗ Missing {len(missing)} dependencies:")
        for m in missing:
            print(f"  - {m}")
        print()
        if "requests" in missing:
            print("Install with: pip install requests")
        return False
    else:
        print("✓ All dependencies available!")
        return True


def check_ollama():
    """Check Ollama availability."""
    import requests

    print("Checking Ollama service...")
    print("-" * 60)

    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=5)
        if response.status_code == 200:
            data = response.json()
            models = data.get("models", [])
            print(f"✓ Ollama is running")
            print(f"  Available models: {len(models)}")
            for model in models:
                name = model.get("name", "unknown")
                size = model.get("size", 0) / (1024**3)
                print(f"    - {name} ({size:.2f} GB)")
            return True
        else:
            print(f"✗ Ollama returned status {response.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        print("✗ Ollama is not running")
        print("  Start with: ollama serve")
        return False
    except Exception as e:
        print(f"✗ Error checking Ollama: {e}")
        return False


def main():
    """Run all checks."""
    print("=" * 60)
    print("Dependency Checker for Full Cycle Test")
    print("=" * 60)
    print()

    deps_ok = check_imports()
    print()
    ollama_ok = check_ollama()
    print()

    print("=" * 60)
    if deps_ok and ollama_ok:
        print("✓ All checks passed! Ready to run test_full_cycle.py")
        print("=" * 60)
        print()
        print("Run the test:")
        print("  python3 test_full_cycle.py")
        return 0
    else:
        print("✗ Some checks failed")
        print("=" * 60)
        print()
        if not deps_ok:
            print("Fix dependencies first:")
            print("  pip install requests")
        if not ollama_ok:
            print("Start Ollama:")
            print("  ollama serve")
            print("Pull a model:")
            print("  ollama pull llama3.2")
        return 1


if __name__ == "__main__":
    sys.exit(main())
