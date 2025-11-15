"""Synchronous high-level LLM client with retry and compression."""

from typing import List, Optional
from llm_infra.types import LLMProvider
from llm_infra.retry import RetryPolicy
from llm_infra.compressor import PromptCompressor


class LLMClientSync:
    """High-level synchronous LLM client with retry and compression."""

    def __init__(
        self,
        provider: LLMProvider,
        retry_policy: Optional[RetryPolicy] = None,
        compressor: Optional[PromptCompressor] = None,
        max_tokens: Optional[int] = None,
    ):
        """Initialize synchronous LLM client.

        Args:
            provider: LLM provider implementation.
            retry_policy: Retry policy for failed requests (None = no retry).
            compressor: Prompt compressor (None = no compression).
            max_tokens: Maximum tokens for prompts (None = no limit).
        """
        self.provider = provider
        self.retry_policy = retry_policy
        self.compressor = compressor
        self.max_tokens = max_tokens

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
    ) -> str:
        """Generate a single completion with retry and compression.

        Args:
            system_prompt: System/instruction prompt.
            user_prompt: User message/query.
            temperature: Sampling temperature.

        Returns:
            Generated text completion.
        """
        system_prompt = self._compress_if_needed(system_prompt)
        user_prompt = self._compress_if_needed(user_prompt)

        complete_func = self.provider.complete
        if self.retry_policy:
            complete_func = self.retry_policy(complete_func)

        return complete_func(system_prompt, user_prompt, temperature)

    def complete_batch(
        self,
        system_prompt: str,
        user_prompts: List[str],
        temperature: float = 0.0,
    ) -> List[str]:
        """Generate completions for multiple prompts with retry and compression.

        Args:
            system_prompt: System/instruction prompt (same for all).
            user_prompts: List of user messages/queries.
            temperature: Sampling temperature.

        Returns:
            List of generated text completions.
        """
        system_prompt = self._compress_if_needed(system_prompt)
        user_prompts = [self._compress_if_needed(p) for p in user_prompts]

        complete_batch_func = self.provider.complete_batch
        if self.retry_policy:
            complete_batch_func = self.retry_policy(complete_batch_func)

        return complete_batch_func(system_prompt, user_prompts, temperature)

    def _compress_if_needed(self, text: str) -> str:
        """Compress text if compressor and max_tokens are configured.

        Args:
            text: Input text.

        Returns:
            Compressed or original text.
        """
        if self.compressor and self.max_tokens:
            return self.compressor.compress(text, self.max_tokens)
        return text
