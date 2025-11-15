"""Ollama local model provider implementation."""

import requests
from typing import List, Dict, Any


class OllamaProvider:
    """Provider for local Ollama models."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama2",
        timeout: int = 120,
    ):
        """Initialize Ollama provider.

        Args:
            base_url: Base URL for Ollama API.
            model: Model name to use.
            timeout: Request timeout in seconds.
        """
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
    ) -> str:
        """Generate a single completion.

        Args:
            system_prompt: System/instruction prompt.
            user_prompt: User message/query.
            temperature: Sampling temperature.

        Returns:
            Generated text completion.
        """
        prompt = f"{system_prompt}\n\n{user_prompt}"
        response = self._make_request(prompt, temperature)
        return response["response"]

    def complete_batch(
        self,
        system_prompt: str,
        user_prompts: List[str],
        temperature: float = 0.0,
    ) -> List[str]:
        """Generate completions for multiple prompts.

        Args:
            system_prompt: System/instruction prompt (same for all).
            user_prompts: List of user messages/queries.
            temperature: Sampling temperature.

        Returns:
            List of generated text completions.
        """
        return [
            self.complete(system_prompt, user_prompt, temperature)
            for user_prompt in user_prompts
        ]

    def _make_request(self, prompt: str, temperature: float) -> Dict[str, Any]:
        """Make HTTP request to Ollama API.

        Args:
            prompt: Combined prompt text.
            temperature: Sampling temperature.

        Returns:
            API response dictionary.

        Raises:
            requests.HTTPError: If request fails.
        """
        payload = {
            "model": self.model,
            "prompt": prompt,
            "temperature": temperature,
            "stream": False,
        }

        response = requests.post(
            f"{self.base_url}/api/generate",
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()
