"""Ollama local model provider implementation."""

import logging
import requests
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


class OllamaProvider:
    """Provider for local Ollama models."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "deepseek-v3.1:671b-cloud",
        timeout: int = 600,
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

        Raises:
            ValueError: If response format is invalid.
            requests.RequestException: If request fails.
        """
        prompt = f"{system_prompt}\n\n{user_prompt}"
        response = self._make_request(prompt, temperature)

        # Validate response structure
        if not isinstance(response, dict):
            raise ValueError(f"Expected dict response from Ollama, got {type(response)}")

        if "response" not in response:
            raise ValueError("Missing 'response' key in Ollama response")

        content = response["response"]
        if not isinstance(content, str):
            raise ValueError(f"Expected string response, got {type(content)}")

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

    def _make_request(self, prompt: str, temperature: float) -> Dict[str, Any]:
        """Make HTTP request to Ollama API.

        Args:
            prompt: Combined prompt text.
            temperature: Sampling temperature.

        Returns:
            API response dictionary.

        Raises:
            requests.Timeout: If request exceeds timeout.
            requests.ConnectionError: If connection fails.
            requests.HTTPError: If HTTP status is 4xx or 5xx.
            ValueError: If response is not valid JSON.
        """
        payload = {
            "model": self.model,
            "prompt": prompt,
            "temperature": temperature,
            "stream": False,
        }

        try:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()

        except requests.exceptions.Timeout as exc:
            logger.error(
                "Timeout calling Ollama API at %s", self.base_url,
                exc_info=(logger.level == logging.DEBUG)
            )
            raise
        except requests.exceptions.ConnectionError as exc:
            logger.error(
                "Connection error calling Ollama API at %s", self.base_url,
                exc_info=(logger.level == logging.DEBUG)
            )
            raise
        except requests.exceptions.HTTPError as exc:
            status_code = exc.response.status_code if exc.response else 'unknown'
            logger.error(
                "HTTP %s from Ollama API at %s", status_code, self.base_url,
                exc_info=(logger.level == logging.DEBUG)
            )
            raise
        except ValueError as exc:
            logger.error(
                "Invalid JSON response from Ollama API at %s", self.base_url,
                exc_info=(logger.level == logging.DEBUG)
            )
            raise


def list_ollama_models(base_url: str) -> list[str]:
    """Retrieve list of available models from Ollama server.

    Args:
        base_url: Base URL for Ollama API (e.g., "http://localhost:11434")

    Returns:
        List of model names available on the server.
        Returns empty list if request fails or server is unreachable.

    Example:
        >>> models = list_ollama_models("http://localhost:11434")
        >>> print(models)
        ['llama3.2', 'deepseek-v3.1:671b-cloud', 'mistral:latest']
    """
    url = f"{base_url.rstrip('/')}/api/tags"

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        # Expected format: {"models": [{"name": "llama3.2", ...}, ...]}
        if not isinstance(data, dict) or "models" not in data:
            logger.warning(
                "Unexpected response format from Ollama API at %s: missing 'models' key",
                url
            )
            return []

        models_list = data.get("models", [])
        if not isinstance(models_list, list):
            logger.warning(
                "Unexpected response format from Ollama API at %s: 'models' is not a list",
                url
            )
            return []

        # Extract model names
        model_names: list[str] = []
        for model in models_list:
            if isinstance(model, dict) and "name" in model:
                model_names.append(model["name"])

        logger.info("Retrieved %d models from Ollama at %s", len(model_names), base_url)
        return model_names

    except requests.exceptions.Timeout:
        logger.warning("Timeout while connecting to Ollama API at %s", url)
        return []
    except requests.exceptions.ConnectionError:
        logger.warning("Connection error while connecting to Ollama API at %s", url)
        return []
    except requests.exceptions.HTTPError as exc:
        logger.warning("HTTP error from Ollama API at %s: %s", url, exc)
        return []
    except ValueError as exc:
        logger.warning("Invalid JSON response from Ollama API at %s: %s", url, exc)
        return []
    except Exception as exc:  # pragma: no cover
        logger.warning("Unexpected error while fetching models from %s: %s", url, exc)
        return []
