"""OpenAI-compatible HTTP API provider implementation."""

import requests
from typing import List, Optional, Dict, Any


class OpenAICompatibleProvider:
    """Provider for OpenAI-compatible HTTP APIs (OpenAI, Azure, vLLM, etc.)."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4",
        timeout: int = 60,
    ):
        """Initialize OpenAI-compatible provider.

        Args:
            api_key: API key for authentication.
            base_url: Base URL for the API endpoint.
            model: Model identifier to use.
            timeout: Request timeout in seconds.
        """
        self.api_key = api_key
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
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        response = self._make_request(messages, temperature)
        return response["choices"][0]["message"]["content"]

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

    def _make_request(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
    ) -> Dict[str, Any]:
        """Make HTTP request to the API.

        Args:
            messages: List of message dictionaries.
            temperature: Sampling temperature.

        Returns:
            API response dictionary.

        Raises:
            requests.HTTPError: If request fails.
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }

        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()
