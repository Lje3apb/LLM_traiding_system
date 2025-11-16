#!/usr/bin/env python3
"""Quick test of Ollama API without using llm_infra package."""

import requests
import json

def test_ollama_direct():
    """Test Ollama API directly with requests library."""

    print("Quick Ollama API Test")
    print("=" * 60)

    base_url = "http://localhost:11434"

    # Test 1: Check if API is available
    print("\n[1] Checking API availability...")
    try:
        response = requests.get(f"{base_url}/api/tags", timeout=5)
        if response.status_code == 200:
            data = response.json()
            models = data.get("models", [])
            print(f"✓ API is available. Found {len(models)} model(s):")
            for model in models:
                name = model.get("name", "unknown")
                size = model.get("size", 0) / (1024**3)  # Convert to GB
                print(f"  - {name} ({size:.2f} GB)")
        else:
            print(f"✗ API returned status code: {response.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        print("✗ Connection refused. Is Ollama running? (ollama serve)")
        return False
    except Exception as e:
        print(f"✗ Error: {e}")
        return False

    if not models:
        print("\n⚠ No models found. Pull a model first:")
        print("  ollama pull llama3.2")
        return False

    # Test 2: Simple generation
    print("\n[2] Testing text generation...")
    model_name = models[0]["name"]
    print(f"Using model: {model_name}")

    try:
        payload = {
            "model": model_name,
            "prompt": "What is 2+2? Answer with just the number.",
            "stream": False,
            "options": {
                "temperature": 0.0
            }
        }

        print("Sending request (this may take a few seconds)...")
        response = requests.post(
            f"{base_url}/api/generate",
            json=payload,
            timeout=60
        )

        if response.status_code == 200:
            data = response.json()
            answer = data.get("response", "").strip()
            print(f"✓ Response: {answer}")

            # Show some stats
            if "total_duration" in data:
                duration = data["total_duration"] / 1e9  # Convert to seconds
                print(f"  Generation time: {duration:.2f}s")
        else:
            print(f"✗ Request failed with status: {response.status_code}")
            print(f"  Response: {response.text}")
            return False

    except requests.exceptions.Timeout:
        print("✗ Request timed out. Model might be too slow or not loaded.")
        return False
    except Exception as e:
        print(f"✗ Error: {e}")
        return False

    print("\n" + "=" * 60)
    print("✓ Ollama is working correctly!")
    print("=" * 60)
    print("\nYou can now run: python3 test_ollama.py")
    return True

if __name__ == "__main__":
    import sys
    success = test_ollama_direct()
    sys.exit(0 if success else 1)
