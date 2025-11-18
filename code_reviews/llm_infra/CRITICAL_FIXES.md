# CRITICAL ISSUE FIXES - LLM Infrastructure

## Issue #1 & #2: Missing Error Handling in _make_request()

### Current Code (providers_openai.py:103-110)
```python
response = requests.post(
    f"{self.base_url}/chat/completions",
    headers=headers,
    json=payload,
    timeout=self.timeout,
)
response.raise_for_status()
return response.json()
```

### Fixed Code
```python
import logging
logger = logging.getLogger(__name__)

def _make_request(self, messages: List[Dict[str, str]], temperature: float) -> Dict[str, Any]:
    """Make HTTP request to the API.
    
    Raises:
        requests.HTTPError: If HTTP status is 4xx or 5xx
        requests.Timeout: If request exceeds timeout
        requests.ConnectionError: If connection fails
        ValueError: If response is not valid JSON
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
```

---

## Issue #3 & #4: Unsafe Response Parsing

### Current Code (providers_openai.py:46-52)
```python
def complete(
    self,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.0,
) -> str:
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    
    response = self._make_request(messages, temperature)
    return response["choices"][0]["message"]["content"]  # UNSAFE!
```

### Fixed Code
```python
def complete(
    self,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.0,
) -> str:
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
```

---

## Issue #6: Overly Broad Exception Catching in retry.py

### Current Code (retry.py:44-62)
```python
@wraps(func)
def wrapper(*args: Any, **kwargs: Any) -> T:
    last_exception = None
    for attempt in range(self.max_retries + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:  # TOO BROAD!
            last_exception = e
            if attempt < self.max_retries:
                delay = min(
                    self.base_delay * (self.exponential_base**attempt),
                    self.max_delay,
                )
                time.sleep(delay)
            else:
                break
    raise last_exception  # type: ignore
```

### Fixed Code
```python
import logging
logger = logging.getLogger(__name__)

def __call__(self, func: Callable[..., T]) -> Callable[..., T]:
    """Decorator to add retry logic to a function."""
    
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> T:
        last_exception: Optional[Exception] = None
        
        for attempt in range(self.max_retries + 1):
            try:
                if attempt > 0:
                    logger.debug(f"Retry attempt {attempt}/{self.max_retries} for {func.__name__}")
                return func(*args, **kwargs)
                
            except (
                requests.RequestException,  # Network errors (timeout, connection, HTTP)
                TimeoutError,               # Timeout errors
                ConnectionError,            # Connection errors
                OSError,                    # Network-related OS errors
            ) as e:
                last_exception = e
                if attempt < self.max_retries:
                    delay = min(
                        self.base_delay * (self.exponential_base**attempt),
                        self.max_delay,
                    )
                    logger.warning(
                        f"Attempt {attempt + 1} failed with {type(e).__name__}: {e}. "
                        f"Retrying in {delay}s..."
                    )
                    time.sleep(delay)
                else:
                    logger.error(f"All {self.max_retries + 1} retry attempts failed")
                    
            except Exception as e:
                # Don't retry on programming errors - fail fast
                logger.error(f"Non-retryable error in {func.__name__}: {type(e).__name__}: {e}")
                raise
        
        # If we get here, all retries were exhausted
        if last_exception:
            raise last_exception
        
        # This should never happen
        raise RuntimeError("Retry loop exhausted without exception or return")
    
    return wrapper
```

---

## Issue #5: Add Error Handling in complete()

### Current Code (providers_ollama.py:30-48)
```python
def complete(
    self,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.0,
) -> str:
    prompt = f"{system_prompt}\n\n{user_prompt}"
    response = self._make_request(prompt, temperature)
    return response["response"]  # UNSAFE!
```

### Fixed Code
```python
import logging
logger = logging.getLogger(__name__)

def complete(
    self,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.0,
) -> str:
    """Generate a single completion.
    
    Raises:
        ValueError: If response format is invalid
        requests.RequestException: If request fails
    """
    try:
        prompt = f"{system_prompt}\n\n{user_prompt}"
        response = self._make_request(prompt, temperature)
        
        # Validate response structure
        if not isinstance(response, dict):
            raise ValueError(f"Expected dict response from Ollama, got {type(response)}")
        
        if "response" not in response:
            raise ValueError("Missing 'response' key in Ollama response")
        
        result = response["response"]
        if not isinstance(result, str):
            raise ValueError(f"Expected string response, got {type(result)}")
        
        return result
        
    except requests.RequestException as exc:
        logger.error(f"Request failed: {exc}", exc_info=True)
        raise
    except ValueError as exc:
        logger.error(f"Invalid response structure: {exc}", exc_info=True)
        raise
```

---

## Complete Implementation Example

Here's a complete refactored OllamaProvider with all fixes:

```python
"""Ollama local model provider implementation."""

import logging
import requests
from typing import List, Dict, Any, Optional

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
            base_url: Base URL for Ollama API (e.g., http://localhost:11434)
            model: Model name to use
            timeout: Request timeout in seconds (default: 600)

        Raises:
            ValueError: If base_url is invalid
        """
        from urllib.parse import urlparse
        
        # Validate URL
        parsed = urlparse(base_url)
        if not parsed.scheme:
            raise ValueError(f"Invalid URL: missing scheme in {base_url}")
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"Invalid URL scheme: {parsed.scheme}")
        if not parsed.netloc:
            raise ValueError(f"Invalid URL: missing host in {base_url}")
        
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        
        # Create session for connection pooling
        self.session = requests.Session()
        logger.info(f"Initialized OllamaProvider: {self.base_url}, model={model}")

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
    ) -> str:
        """Generate a single completion.

        Args:
            system_prompt: System/instruction prompt
            user_prompt: User message/query
            temperature: Sampling temperature (0.0 = deterministic)

        Returns:
            Generated text completion

        Raises:
            ValueError: If response format is invalid
            requests.RequestException: If request fails
        """
        try:
            prompt = f"{system_prompt}\n\n{user_prompt}"
            response = self._make_request(prompt, temperature)
            
            # Validate response
            if not isinstance(response, dict):
                raise ValueError(f"Expected dict, got {type(response)}")
            if "response" not in response:
                raise ValueError("Missing 'response' key in Ollama response")
            if not isinstance(response["response"], str):
                raise ValueError(f"Expected string content, got {type(response['response'])}")
            
            return response["response"]
            
        except (ValueError, requests.RequestException) as exc:
            logger.error(f"Failed to generate completion: {exc}", exc_info=True)
            raise

    def complete_batch(
        self,
        system_prompt: str,
        user_prompts: List[str],
        temperature: float = 0.0,
    ) -> List[str]:
        """Generate completions for multiple prompts.

        Args:
            system_prompt: System/instruction prompt (same for all)
            user_prompts: List of user messages/queries
            temperature: Sampling temperature

        Returns:
            List of generated text completions

        Note:
            Fails on first error. Consider wrapping in retry logic for robustness.
        """
        results = []
        for i, user_prompt in enumerate(user_prompts):
            try:
                result = self.complete(system_prompt, user_prompt, temperature)
                results.append(result)
            except Exception as exc:
                logger.error(f"Failed on item {i}/{len(user_prompts)}: {exc}")
                raise
        return results

    def _make_request(self, prompt: str, temperature: float) -> Dict[str, Any]:
        """Make HTTP request to Ollama API.

        Args:
            prompt: Combined prompt text
            temperature: Sampling temperature

        Returns:
            API response dictionary with structure: {"response": str}

        Raises:
            requests.HTTPError: If HTTP status is 4xx or 5xx
            requests.Timeout: If request exceeds timeout
            requests.ConnectionError: If connection fails
            ValueError: If response is not valid JSON
        """
        payload = {
            "model": self.model,
            "prompt": prompt,
            "temperature": temperature,
            "stream": False,
        }

        try:
            response = self.session.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.Timeout as exc:
            logger.error(f"Timeout at {self.base_url} (timeout={self.timeout}s)", exc_info=True)
            raise
        except requests.exceptions.ConnectionError as exc:
            logger.error(f"Connection error at {self.base_url}", exc_info=True)
            raise
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response else 'unknown'
            logger.error(f"HTTP {status} from {self.base_url}: {exc.response.text if exc.response else ''}", exc_info=True)
            raise
        except ValueError as exc:
            logger.error(f"Invalid JSON response from {self.base_url}", exc_info=True)
            raise

    def __del__(self):
        """Clean up session on object destruction."""
        if hasattr(self, 'session'):
            self.session.close()
```

---

## Testing Recommendations

Add tests for all error cases:

```python
import pytest
from unittest.mock import patch, MagicMock
import requests

def test_ollama_provider_timeout():
    """Test timeout handling."""
    provider = OllamaProvider()
    with patch.object(provider.session, 'post') as mock_post:
        mock_post.side_effect = requests.Timeout("timeout")
        with pytest.raises(requests.Timeout):
            provider.complete("sys", "user")

def test_ollama_provider_invalid_response():
    """Test malformed response handling."""
    provider = OllamaProvider()
    with patch.object(provider.session, 'post') as mock_post:
        mock_post.return_value.json.return_value = {"wrong_key": "value"}
        with pytest.raises(ValueError, match="Missing 'response'"):
            provider.complete("sys", "user")

def test_ollama_provider_invalid_url():
    """Test URL validation."""
    with pytest.raises(ValueError, match="Invalid URL"):
        OllamaProvider(base_url="not-a-url")

def test_retry_policy_catches_timeout():
    """Test retry policy handles timeouts."""
    policy = RetryPolicy(max_retries=2, base_delay=0.1)
    call_count = 0
    
    @policy
    def failing_func():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise requests.Timeout("timeout")
        return "success"
    
    result = failing_func()
    assert result == "success"
    assert call_count == 3  # 2 retries + 1 success

def test_retry_policy_fails_fast_on_programming_error():
    """Test retry policy doesn't retry programming errors."""
    policy = RetryPolicy(max_retries=3, base_delay=0.01)
    call_count = 0
    
    @policy
    def failing_func():
        nonlocal call_count
        call_count += 1
        raise ValueError("programming error")
    
    with pytest.raises(ValueError, match="programming error"):
        failing_func()
    
    assert call_count == 1  # No retries, just one call
```

