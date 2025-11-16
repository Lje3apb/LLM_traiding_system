#!/usr/bin/env python3
"""Check environment variables for API keys."""

import os

print("Checking environment variables...")
print("=" * 60)

api_keys = {
    "CRYPTOPANIC_API_KEY": os.getenv("CRYPTOPANIC_API_KEY"),
    "NEWSAPI_KEY": os.getenv("NEWSAPI_KEY"),
}

for key, value in api_keys.items():
    if value:
        masked = value[:4] + "***" + value[-4:] if len(value) > 8 else "***"
        print(f"✓ {key}: {masked}")
    else:
        print(f"✗ {key}: NOT SET")

print("=" * 60)

if not any(api_keys.values()):
    print("\nNo API keys found!")
    print("\nTo fix:")
    print("1. In same terminal where you run the test, execute:")
    print("   export CRYPTOPANIC_API_KEY='your_key'")
    print("   export NEWSAPI_KEY='your_key'")
    print("   python3 test_full_cycle.py --real-data")
    print("\n2. Or create .env file and use:")
    print("   source .env")
    print("   python3 test_full_cycle.py --real-data")
