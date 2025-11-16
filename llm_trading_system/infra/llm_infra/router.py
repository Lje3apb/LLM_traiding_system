"""LLM router to select models based on task type."""

from typing import Dict, Optional
from llm_infra.types import LLMProvider


class LLMRouter:
    """Route requests to appropriate LLM providers based on task type."""

    def __init__(
        self,
        providers: Dict[str, LLMProvider],
        default_provider: Optional[str] = None,
    ):
        """Initialize LLM router.

        Args:
            providers: Dictionary mapping task names to provider instances.
            default_provider: Default provider key to use if task not found.

        Raises:
            ValueError: If providers dict is empty or default_provider is invalid.
        """
        if not providers:
            raise ValueError("At least one provider must be specified")

        self.providers = providers

        if default_provider is None:
            self.default_provider = next(iter(providers.keys()))
        else:
            if default_provider not in providers:
                raise ValueError(f"Default provider '{default_provider}' not in providers")
            self.default_provider = default_provider

    def get_provider(self, task: str) -> LLMProvider:
        """Get provider for a specific task.

        Args:
            task: Task identifier.

        Returns:
            LLM provider for the task.
        """
        return self.providers.get(task, self.providers[self.default_provider])

    def complete(
        self,
        task: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
    ) -> str:
        """Route completion request to appropriate provider.

        Args:
            task: Task identifier to select provider.
            system_prompt: System/instruction prompt.
            user_prompt: User message/query.
            temperature: Sampling temperature.

        Returns:
            Generated text completion.
        """
        provider = self.get_provider(task)
        return provider.complete(system_prompt, user_prompt, temperature)

    def add_provider(self, task: str, provider: LLMProvider) -> None:
        """Add or update a provider for a task.

        Args:
            task: Task identifier.
            provider: LLM provider instance.
        """
        self.providers[task] = provider

    def remove_provider(self, task: str) -> None:
        """Remove a provider for a task.

        Args:
            task: Task identifier.

        Raises:
            ValueError: If trying to remove the last provider or default provider.
        """
        if len(self.providers) == 1:
            raise ValueError("Cannot remove the last provider")
        if task == self.default_provider:
            raise ValueError("Cannot remove default provider")
        if task in self.providers:
            del self.providers[task]
