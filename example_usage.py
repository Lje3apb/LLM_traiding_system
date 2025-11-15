"""Example usage of the llm_infra package."""

import os
from llm_infra import (
    OpenAICompatibleProvider,
    OllamaProvider,
    LLMClientSync,
    RetryPolicy,
    PromptCompressor,
    LLMRouter,
)


def example_basic_provider():
    """Example: Basic provider usage."""
    print("=== Basic Provider Usage ===")

    # Using OpenAI-compatible provider
    api_key = os.getenv("OPENAI_API_KEY", "your-api-key-here")
    provider = OpenAICompatibleProvider(
        api_key=api_key,
        model="gpt-3.5-turbo",
    )

    response = provider.complete(
        system_prompt="You are a helpful assistant.",
        user_prompt="What is the capital of France?",
        temperature=0.0,
    )
    print(f"Response: {response}\n")


def example_with_retry():
    """Example: Using client with retry policy."""
    print("=== Client with Retry ===")

    api_key = os.getenv("OPENAI_API_KEY", "your-api-key-here")
    provider = OpenAICompatibleProvider(api_key=api_key, model="gpt-3.5-turbo")

    retry_policy = RetryPolicy(max_retries=3, base_delay=1.0)
    client = LLMClientSync(provider=provider, retry_policy=retry_policy)

    response = client.complete(
        system_prompt="You are a helpful assistant.",
        user_prompt="Explain quantum computing in one sentence.",
        temperature=0.0,
    )
    print(f"Response: {response}\n")


def example_with_compression():
    """Example: Using client with prompt compression."""
    print("=== Client with Compression ===")

    api_key = os.getenv("OPENAI_API_KEY", "your-api-key-here")
    provider = OpenAICompatibleProvider(api_key=api_key, model="gpt-3.5-turbo")

    compressor = PromptCompressor(chars_per_token=4.0)
    client = LLMClientSync(
        provider=provider,
        compressor=compressor,
        max_tokens=100,
    )

    long_prompt = "Explain machine learning. " * 50  # Very long prompt
    print(f"Original prompt length: {len(long_prompt)} chars")

    response = client.complete(
        system_prompt="You are a helpful assistant.",
        user_prompt=long_prompt,
        temperature=0.0,
    )
    print(f"Response: {response}\n")


def example_batch_completion():
    """Example: Batch completion."""
    print("=== Batch Completion ===")

    api_key = os.getenv("OPENAI_API_KEY", "your-api-key-here")
    provider = OpenAICompatibleProvider(api_key=api_key, model="gpt-3.5-turbo")

    client = LLMClientSync(provider=provider)

    user_prompts = [
        "What is 2+2?",
        "What is the speed of light?",
        "Who wrote Romeo and Juliet?",
    ]

    responses = client.complete_batch(
        system_prompt="You are a helpful assistant. Answer briefly.",
        user_prompts=user_prompts,
        temperature=0.0,
    )

    for prompt, response in zip(user_prompts, responses):
        print(f"Q: {prompt}")
        print(f"A: {response}\n")


def example_router():
    """Example: Router with multiple providers."""
    print("=== Router Example ===")

    api_key = os.getenv("OPENAI_API_KEY", "your-api-key-here")

    # Create providers for different tasks
    fast_provider = OpenAICompatibleProvider(
        api_key=api_key,
        model="gpt-3.5-turbo",
    )

    smart_provider = OpenAICompatibleProvider(
        api_key=api_key,
        model="gpt-4",
    )

    # Create router
    router = LLMRouter(
        providers={
            "simple": fast_provider,
            "complex": smart_provider,
            "coding": smart_provider,
        },
        default_provider="simple",
    )

    # Use router for different tasks
    response1 = router.complete(
        task="simple",
        system_prompt="You are a helpful assistant.",
        user_prompt="What is 5+3?",
    )
    print(f"Simple task response: {response1}")

    response2 = router.complete(
        task="complex",
        system_prompt="You are a helpful assistant.",
        user_prompt="Explain the theory of relativity briefly.",
    )
    print(f"Complex task response: {response2}\n")


def example_ollama():
    """Example: Using Ollama for local models."""
    print("=== Ollama Local Model ===")

    try:
        provider = OllamaProvider(model="llama2")

        response = provider.complete(
            system_prompt="You are a helpful assistant.",
            user_prompt="What is Python?",
            temperature=0.0,
        )
        print(f"Response: {response}\n")
    except Exception as e:
        print(f"Ollama not available: {e}\n")


if __name__ == "__main__":
    print("LLM Infrastructure Examples\n")

    # Note: These examples require valid API keys or running services
    # Uncomment the examples you want to run:

    # example_basic_provider()
    # example_with_retry()
    # example_with_compression()
    # example_batch_completion()
    # example_router()
    # example_ollama()

    print("Examples complete!")
    print("\nTo run these examples, uncomment them and set OPENAI_API_KEY environment variable.")
