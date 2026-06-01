"""Chat client protocol — sends messages to an LLM and returns text."""

from typing import Protocol


class ChatClient(Protocol):
    """Interface for LLM chat completion."""

    def send(
        self,
        messages: list[dict],
        max_tokens: int = 500,
        temperature: float = 0.3,
    ) -> str: ...
