"""Shared LLM chat completion wrapper."""

import os

from huggingface_hub import InferenceClient

from kapsula.infrastructure.logging_config import get_logger

logger = get_logger(__name__)

# Default timeout in seconds for all LLM calls (5 min for planning sub-queries)
DEFAULT_LLM_TIMEOUT = int(os.environ.get("KAPSULA_LLM_TIMEOUT", "300"))


class ChatClientError(RuntimeError):
    """Domain-level error raised when an LLM call fails.

    Translating the HF SDK's exception types into one domain exception means
    callers (IntelligentSearcher, planners, selectors) depend on a single
    error type from our own layer, not on ``huggingface_hub`` internals
    (closes L5: the previous wrapper caught, logged, and re-raised the same
    exception — it added noise without translating anything).
    """


class HuggingFaceChatClient:
    """Thin wrapper around InferenceClient.chat.completions."""

    def __init__(self, token: str, model: str, timeout: int | None = None):
        self._client = InferenceClient(
            token=token, timeout=timeout or DEFAULT_LLM_TIMEOUT
        )
        self._model = model

    def send(
        self,
        messages: list[dict],
        max_tokens: int = 500,
        temperature: float = 0.3,
    ) -> str:
        """Send a chat completion request and return the assistant message text.

        Raises:
            ChatClientError: on any failure talking to the inference backend.
        """
        try:
            completion = self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return completion.choices[0].message.content
        except Exception as exc:
            logger.error("LLM call failed: %s", exc)
            raise ChatClientError(str(exc)) from exc
