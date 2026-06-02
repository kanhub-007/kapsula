"""Shared LLM chat completion wrapper."""

import logging
import os
from huggingface_hub import InferenceClient
from huggingface_hub.errors import HfHubHTTPError

logger = logging.getLogger(__name__)

# Default timeout in seconds for all LLM calls (5 min for planning sub-queries)
DEFAULT_LLM_TIMEOUT = int(os.environ.get("DOCSEARCH_LLM_TIMEOUT", "300"))


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
        try:
            completion = self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return completion.choices[0].message.content
        except HfHubHTTPError as e:
            logger.error(
                f"HuggingFace API error (status {getattr(e, 'response', {}).get('status_code', '?')}): {e}"
            )
            raise
        except Exception as e:
            logger.error(f"LLM call failed: {e}", exc_info=True)
            raise
