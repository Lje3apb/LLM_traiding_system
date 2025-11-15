"""Composable LLM infrastructure primitives for sync and async workflows."""

from __future__ import annotations

import asyncio
import os
import time
from typing import Awaitable, Callable, Dict, List, Protocol, Tuple, TypeVar

import requests

try:  # pragma: no cover - optional dependency
    from openai import OpenAI
except ImportError:  # pragma: no cover - optional dependency
    OpenAI = None  # type: ignore

try:  # pragma: no cover - optional dependency
    import httpx
except ImportError:  # pragma: no cover - optional dependency
    httpx = None  # type: ignore


class LLMProvider(Protocol):
    """Synchronous LLM provider interface."""

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
    ) -> str:
        """Generate a completion for a single prompt."""

    def complete_batch(
        self,
        system_prompt: str,
        user_prompts: List[str],
        temperature: float = 0.0,
    ) -> List[str]:
        """Generate completions for multiple prompts in a batch."""


class AsyncLLMProvider(Protocol):
    """Asynchronous LLM provider interface."""

    async def acomplete(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
    ) -> str:
        """Asynchronously generate a completion for a single prompt."""

    async def acomplete_batch(
        self,
        system_prompt: str,
        user_prompts: List[str],
        temperature: float = 0.0,
    ) -> List[str]:
        """Asynchronously generate completions for multiple prompts."""


_T = TypeVar("_T")


class RetryPolicy:
    """Sync retry helper with exponential backoff for provider calls."""

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 0.5,
        max_delay: float = 10.0,
        retry_on: Tuple[type[Exception], ...] = (Exception,),
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if base_delay <= 0:
            raise ValueError("base_delay must be positive")
        if max_delay < base_delay:
            raise ValueError("max_delay must be >= base_delay")
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.retry_on = retry_on

    def run(self, func: Callable[[], _T]) -> _T:
        """Execute *func* with retries, re-raising the last exception on failure."""

        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return func()
            except self.retry_on as exc:  # type: ignore[misc]
                last_exc = exc
                if attempt >= self.max_retries:
                    raise
                delay = min(self.max_delay, self.base_delay * (2**attempt))
                time.sleep(delay)
        if last_exc is not None:  # pragma: no cover
            raise last_exc
        raise RuntimeError("RetryPolicy.run exited without executing func")


class AsyncRetryPolicy(RetryPolicy):
    """Async variant of RetryPolicy using asyncio sleep."""

    async def arun(self, func: Callable[[], Awaitable[_T] | _T]) -> _T:
        """Execute *func* with retries, awaiting async callables when needed."""

        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                result = func()
                if asyncio.iscoroutine(result):
                    return await result  # type: ignore[return-value]
                return result  # type: ignore[return-value]
            except self.retry_on as exc:  # type: ignore[misc]
                last_exc = exc
                if attempt >= self.max_retries:
                    raise
                delay = min(self.max_delay, self.base_delay * (2**attempt))
                await asyncio.sleep(delay)
        if last_exc is not None:  # pragma: no cover
            raise last_exc
        raise RuntimeError("AsyncRetryPolicy.arun exited without executing func")


class OpenAICompatibleProvider(LLMProvider, AsyncLLMProvider):
    """Provider for OpenAI-compatible chat APIs supporting sync and async."""

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 30.0,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required for OpenAICompatibleProvider")
        if OpenAI is None:
            raise RuntimeError("openai package is required for OpenAICompatibleProvider")
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = OpenAI(api_key=api_key, base_url=self.base_url, timeout=timeout)

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
        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
        )
        return (response.choices[0].message.content or "").strip()

    def complete_batch(
        self,
        system_prompt: str,
        user_prompts: List[str],
        temperature: float = 0.0,
    ) -> List[str]:
        return [
            self.complete(system_prompt=system_prompt, user_prompt=prompt, temperature=temperature)
            for prompt in user_prompts
        ]

    async def acomplete(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
    ) -> str:
        if httpx is None:
            raise RuntimeError("httpx package is required for async OpenAICompatibleProvider")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
        return (data["choices"][0]["message"]["content"] or "").strip()

    async def acomplete_batch(
        self,
        system_prompt: str,
        user_prompts: List[str],
        temperature: float = 0.0,
    ) -> List[str]:
        results: List[str] = []
        for prompt in user_prompts:
            results.append(
                await self.acomplete(
                    system_prompt=system_prompt,
                    user_prompt=prompt,
                    temperature=temperature,
                )
            )
        return results


class OllamaProvider(LLMProvider, AsyncLLMProvider):
    """Provider for local Ollama chat models over HTTP."""

    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:11434",
        timeout: float = 60.0,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _format_messages(self, system_prompt: str, user_prompt: str) -> List[Dict[str, str]]:
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
    ) -> str:
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": self.model,
            "messages": self._format_messages(system_prompt, user_prompt),
            "options": {"temperature": temperature},
            "stream": False,
        }
        response = requests.post(url, json=payload, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        return (data["message"]["content"] or "").strip()

    def complete_batch(
        self,
        system_prompt: str,
        user_prompts: List[str],
        temperature: float = 0.0,
    ) -> List[str]:
        return [
            self.complete(system_prompt=system_prompt, user_prompt=prompt, temperature=temperature)
            for prompt in user_prompts
        ]

    async def acomplete(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
    ) -> str:
        if httpx is None:
            raise RuntimeError("httpx package is required for async OllamaProvider")
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": self.model,
            "messages": self._format_messages(system_prompt, user_prompt),
            "options": {"temperature": temperature},
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
        return (data["message"]["content"] or "").strip()

    async def acomplete_batch(
        self,
        system_prompt: str,
        user_prompts: List[str],
        temperature: float = 0.0,
    ) -> List[str]:
        results: List[str] = []
        for prompt in user_prompts:
            results.append(
                await self.acomplete(
                    system_prompt=system_prompt,
                    user_prompt=prompt,
                    temperature=temperature,
                )
            )
        return results


class PromptCompressor:
    """Approximate token-based prompt truncator favoring recent user content."""

    _CHARS_PER_TOKEN = 4

    def __init__(self, max_tokens: int, safety_margin: int = 256) -> None:
        if max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        if safety_margin < 0:
            raise ValueError("safety_margin must be non-negative")
        self.max_tokens = max_tokens
        self.safety_margin = safety_margin

    def _approx_tokens(self, text: str) -> int:
        return max(0, (len(text) + self._CHARS_PER_TOKEN - 1) // self._CHARS_PER_TOKEN)

    def _trim_from_start(self, text: str, tokens: int) -> Tuple[str, int]:
        if tokens <= 0 or not text:
            return text, 0
        chars = min(len(text), tokens * self._CHARS_PER_TOKEN)
        trimmed = text[chars:]
        removed_tokens = max(0, self._approx_tokens(text) - self._approx_tokens(trimmed))
        remaining = max(0, tokens - removed_tokens)
        return trimmed, remaining

    def truncate(self, system_prompt: str, user_prompt: str) -> Tuple[str, str]:
        """Return prompts constrained by max_tokens minus safety margin."""

        limit = max(self.max_tokens - self.safety_margin, 0)
        system_tokens = self._approx_tokens(system_prompt)
        user_tokens = self._approx_tokens(user_prompt)
        total_tokens = system_tokens + user_tokens
        if total_tokens <= limit:
            return system_prompt, user_prompt

        tokens_to_remove = total_tokens - limit
        truncated_user = user_prompt

        sections = truncated_user.split("\n\n") if truncated_user else []
        while tokens_to_remove > 0 and len(sections) > 1:
            removed = sections.pop(0)
            tokens_to_remove -= self._approx_tokens(removed)
        tokens_to_remove = max(0, tokens_to_remove)
        truncated_user = "\n\n".join(sections)

        if tokens_to_remove > 0 and truncated_user:
            truncated_user, tokens_to_remove = self._trim_from_start(truncated_user, tokens_to_remove)

        if tokens_to_remove > 0 and system_prompt:
            system_prompt, tokens_to_remove = self._trim_from_start(system_prompt, tokens_to_remove)

        return system_prompt, truncated_user


class LLMClientSync:
    """High-level synchronous client combining provider, retries, and compression."""

    def __init__(
        self,
        provider: LLMProvider,
        retry_policy: RetryPolicy | None = None,
        compressor: PromptCompressor | None = None,
    ) -> None:
        self._provider = provider
        self._retry_policy = retry_policy
        self._compressor = compressor

    def _prepare_prompts(self, system_prompt: str, user_prompt: str) -> Tuple[str, str]:
        if self._compressor:
            return self._compressor.truncate(system_prompt, user_prompt)
        return system_prompt, user_prompt

    def run(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
    ) -> str:
        sys_prompt, usr_prompt = self._prepare_prompts(system_prompt, user_prompt)
        if self._retry_policy:
            return self._retry_policy.run(
                lambda: self._provider.complete(
                    system_prompt=sys_prompt,
                    user_prompt=usr_prompt,
                    temperature=temperature,
                )
            )
        return self._provider.complete(
            system_prompt=sys_prompt,
            user_prompt=usr_prompt,
            temperature=temperature,
        )

    def run_batch(
        self,
        system_prompt: str,
        user_prompts: List[str],
        temperature: float = 0.0,
    ) -> List[str]:
        def _call() -> List[str]:
            prepared_prompts = [
                self._prepare_prompts(system_prompt, prompt)[1]
                for prompt in user_prompts
            ]
            sys_prompt = system_prompt
            if self._compressor:
                sys_prompt, _ = self._prepare_prompts(system_prompt, "")
            return self._provider.complete_batch(
                system_prompt=sys_prompt,
                user_prompts=prepared_prompts,
                temperature=temperature,
            )

        if self._retry_policy:
            return self._retry_policy.run(_call)
        return _call()


class LLMClientAsync:
    """High-level asynchronous client combining provider, retries, and compression."""

    def __init__(
        self,
        provider: AsyncLLMProvider,
        retry_policy: AsyncRetryPolicy | None = None,
        compressor: PromptCompressor | None = None,
    ) -> None:
        self._provider = provider
        self._retry_policy = retry_policy
        self._compressor = compressor

    def _prepare_prompts(self, system_prompt: str, user_prompt: str) -> Tuple[str, str]:
        if self._compressor:
            return self._compressor.truncate(system_prompt, user_prompt)
        return system_prompt, user_prompt

    async def run(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
    ) -> str:
        sys_prompt, usr_prompt = self._prepare_prompts(system_prompt, user_prompt)

        async def _call() -> str:
            return await self._provider.acomplete(
                system_prompt=sys_prompt,
                user_prompt=usr_prompt,
                temperature=temperature,
            )

        if self._retry_policy:
            return await self._retry_policy.arun(_call)
        return await _call()

    async def run_batch(
        self,
        system_prompt: str,
        user_prompts: List[str],
        temperature: float = 0.0,
    ) -> List[str]:
        async def _call() -> List[str]:
            prepared_prompts = [
                self._prepare_prompts(system_prompt, prompt)[1]
                for prompt in user_prompts
            ]
            sys_prompt = system_prompt
            if self._compressor:
                sys_prompt, _ = self._prepare_prompts(system_prompt, "")
            return await self._provider.acomplete_batch(
                system_prompt=sys_prompt,
                user_prompts=prepared_prompts,
                temperature=temperature,
            )

        if self._retry_policy:
            return await self._retry_policy.arun(_call)
        return await _call()


class LLMRouter:
    """Router for mapping task names to LLMClientSync instances."""

    def __init__(self) -> None:
        self._clients: Dict[str, LLMClientSync] = {}

    def register(self, task: str, client: LLMClientSync) -> None:
        self._clients[task] = client

    def get(self, task: str) -> LLMClientSync:
        if task not in self._clients:
            raise KeyError(f"No client registered for task '{task}'")
        return self._clients[task]

    def run(
        self,
        task: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
    ) -> str:
        client = self.get(task)
        return client.run(system_prompt=system_prompt, user_prompt=user_prompt, temperature=temperature)


class LLMRouterAsync:
    """Router for mapping task names to LLMClientAsync instances."""

    def __init__(self) -> None:
        self._clients: Dict[str, LLMClientAsync] = {}

    def register(self, task: str, client: LLMClientAsync) -> None:
        self._clients[task] = client

    def get(self, task: str) -> LLMClientAsync:
        if task not in self._clients:
            raise KeyError(f"No async client registered for task '{task}'")
        return self._clients[task]

    async def run(
        self,
        task: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
    ) -> str:
        client = self.get(task)
        return await client.run(system_prompt=system_prompt, user_prompt=user_prompt, temperature=temperature)


if __name__ == "__main__":
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY environment variable is required for the demo")

    provider = OpenAICompatibleProvider(
        model="gpt-4.1-mini",
        api_key=api_key,
    )
    compressor = PromptCompressor(max_tokens=4000)
    retry_policy = RetryPolicy(max_retries=2, base_delay=0.5, max_delay=2.0)
    client = LLMClientSync(provider=provider, retry_policy=retry_policy, compressor=compressor)

    system_prompt = "You are a test assistant."
    user_prompt = "Say hello in one short sentence."
    print(client.run(system_prompt=system_prompt, user_prompt=user_prompt))

    router = LLMRouter()
    router.register("regime_estimation", client)
    print(
        router.run(
            task="regime_estimation",
            system_prompt=system_prompt,
            user_prompt="Respond with a short greeting routed through the LLMRouter.",
        )
    )
