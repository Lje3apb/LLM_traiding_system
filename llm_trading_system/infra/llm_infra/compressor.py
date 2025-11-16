"""Prompt compression utilities to fit within token limits."""

from typing import Optional


class PromptCompressor:
    """Compress prompts to fit within maximum token limits."""

    def __init__(self, chars_per_token: float = 4.0):
        """Initialize prompt compressor.

        Args:
            chars_per_token: Approximate characters per token (rough heuristic).
        """
        self.chars_per_token = chars_per_token

    def compress(
        self,
        text: str,
        max_tokens: Optional[int] = None,
        strategy: str = "truncate",
    ) -> str:
        """Compress text to fit within token limit.

        Args:
            text: Input text to compress.
            max_tokens: Maximum number of tokens allowed (None = no limit).
            strategy: Compression strategy ('truncate' or 'summarize').

        Returns:
            Compressed text.
        """
        if max_tokens is None:
            return text

        max_chars = int(max_tokens * self.chars_per_token)

        if len(text) <= max_chars:
            return text

        if strategy == "truncate":
            return self._truncate(text, max_chars)
        elif strategy == "summarize":
            return self._summarize(text, max_chars)
        else:
            raise ValueError(f"Unknown compression strategy: {strategy}")

    def _truncate(self, text: str, max_chars: int) -> str:
        """Truncate text to maximum characters.

        Args:
            text: Text to truncate.
            max_chars: Maximum characters.

        Returns:
            Truncated text with ellipsis.
        """
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 3] + "..."

    def _summarize(self, text: str, max_chars: int) -> str:
        """Summarize text by taking start and end portions.

        Args:
            text: Text to summarize.
            max_chars: Maximum characters.

        Returns:
            Summarized text with middle section omitted.
        """
        if len(text) <= max_chars:
            return text

        marker = "\n...[truncated]...\n"
        available = max_chars - len(marker)
        start_chars = available // 2
        end_chars = available - start_chars

        return text[:start_chars] + marker + text[-end_chars:]

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count for text.

        Args:
            text: Input text.

        Returns:
            Estimated token count.
        """
        return int(len(text) / self.chars_per_token)
