"""OpenAI-compatible HTTP API provider implementation."""

import logging
import requests
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)


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

        Raises:
            ValueError: If response format is invalid.
            requests.RequestException: If request fails.
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        response = self._make_request(messages, temperature)

        # Validate response structure
        if not isinstance(response, dict):
            raise ValueError(f"Expected dict response from OpenAI, got {type(response)}")

        if "choices" not in response:
            raise ValueError("Missing 'choices' key in OpenAI response")

        choices = response["choices"]
        if not isinstance(choices, list) or not choices:
            raise ValueError(f"Expected non-empty list for 'choices', got {type(choices)}")

        choice = choices[0]
        if not isinstance(choice, dict):
            raise ValueError(f"Expected dict choice, got {type(choice)}")

        if "message" not in choice:
            raise ValueError("Missing 'message' key in choice")

        message = choice["message"]
        if not isinstance(message, dict):
            raise ValueError(f"Expected dict message, got {type(message)}")

        if "content" not in message:
            raise ValueError("Missing 'content' key in message")

        content = message["content"]
        if not isinstance(content, str):
            raise ValueError(f"Expected string content, got {type(content)}")

        return content

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
            requests.Timeout: If request exceeds timeout.
            requests.ConnectionError: If connection fails.
            requests.HTTPError: If HTTP status is 4xx or 5xx.
            ValueError: If response is not valid JSON.
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

        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()

        except requests.exceptions.Timeout as exc:
            logger.error("Timeout calling OpenAI API at %s", self.base_url, exc_info=True)
            raise
        except requests.exceptions.ConnectionError as exc:
            logger.error("Connection error calling OpenAI API at %s", self.base_url, exc_info=True)
            raise
        except requests.exceptions.HTTPError as exc:
            status_code = exc.response.status_code if exc.response else 'unknown'
            logger.error("HTTP %s from OpenAI API at %s", status_code, self.base_url, exc_info=True)
            raise
        except ValueError as exc:
            logger.error("Invalid JSON response from OpenAI API at %s", self.base_url, exc_info=True)
            raise
