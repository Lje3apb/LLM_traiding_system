#!/usr/bin/env python3
"""Test script for llm_infra package with Ollama."""

import sys
from llm_trading_system.infra.llm_infra import OllamaProvider, LLMClientSync, RetryPolicy

def main():
    """Test Ollama integration with llm_infra package."""

    print("=" * 60)
    print("Testing llm_infra with Ollama")
    print("=" * 60)

    # Test 1: Basic Ollama provider
    print("\n[Test 1] Basic Ollama Provider")
    print("-" * 60)
    try:
        provider = OllamaProvider(
            base_url="http://localhost:11434",
            model="gpt-oss:20b",  # Change to your model name
            timeout=120
        )

        response = provider.complete(
            system_prompt="You are a helpful AI assistant.",
            user_prompt="What is Python? Answer in one sentence.",
            temperature=0.0
        )
        print(f"✓ Response: {response}")
    except Exception as e:
        print(f"✗ Error: {e}")
        print("\nPossible issues:")
        print("1. Ollama service not running (run: ollama serve)")
        print("2. Model not available (run: ollama pull gpt-oss:20b)")
        print("3. Wrong base URL or port")
        return 1

    # Test 2: Client with retry policy
    print("\n[Test 2] Client with Retry Policy")
    print("-" * 60)
    try:
        provider = OllamaProvider(model="gpt-oss:20b")
        retry_policy = RetryPolicy(max_retries=2, base_delay=0.5)
        client = LLMClientSync(provider=provider, retry_policy=retry_policy)

        response = client.complete(
            system_prompt="You are a helpful AI assistant.",
            user_prompt="Explain machine learning in 10 words.",
            temperature=0.3
        )
        print(f"✓ Response: {response}")
    except Exception as e:
        print(f"✗ Error: {e}")
        return 1

    # Test 3: Batch completion
    print("\n[Test 3] Batch Completion")
    print("-" * 60)
    try:
        provider = OllamaProvider(model="gpt-oss:20b")
        client = LLMClientSync(provider=provider)

        questions = [
            "What is 5 + 3?",
            "What color is the sky?",
            "Name one programming language."
        ]

        print("Questions:")
        for i, q in enumerate(questions, 1):
            print(f"  {i}. {q}")

        responses = client.complete_batch(
            system_prompt="You are a helpful AI assistant. Answer very briefly.",
            user_prompts=questions,
            temperature=0.0
        )

        print("\nAnswers:")
        for i, (q, a) in enumerate(zip(questions, responses), 1):
            print(f"  {i}. Q: {q}")
            print(f"     A: {a}")
    except Exception as e:
        print(f"✗ Error: {e}")
        return 1

    # Test 4: Different models (if available)
    print("\n[Test 4] Testing Different Models")
    print("-" * 60)
    test_models = ["gpt-oss:20b", "llama2", "mistral", "phi"]

    for model_name in test_models:
        try:
            provider = OllamaProvider(model=model_name, timeout=10)
            response = provider.complete(
                system_prompt="You are a helpful assistant.",
                user_prompt="Say 'Hello' in one word.",
                temperature=0.0
            )
            print(f"✓ {model_name:15s}: {response[:50]}...")
        except Exception as e:
            print(f"✗ {model_name:15s}: Not available or error - {str(e)[:30]}")

    print("\n" + "=" * 60)
    print("All tests completed successfully!")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
