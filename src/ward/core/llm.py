"""Shared LLM client construction and usage normalization."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from anthropic import Anthropic

from ward.core.config import get_config


LLM_TIMEOUT_SECONDS = 60.0


def create_anthropic_client() -> Anthropic:
    cfg = get_config().llm
    return Anthropic(api_key=cfg.api_key, base_url=cfg.base_url, timeout=LLM_TIMEOUT_SECONDS, max_retries=2)


def extract_llm_usage(response: Any) -> dict[str, Any]:
    raw = getattr(response, "usage", None)
    input_tokens = int(getattr(raw, "input_tokens", 0) or 0)
    output_tokens = int(getattr(raw, "output_tokens", 0) or 0)
    cache_read = int(getattr(raw, "cache_read_input_tokens", 0) or 0)
    cache_creation = int(getattr(raw, "cache_creation_input_tokens", 0) or 0)
    total_input = input_tokens + cache_read + cache_creation
    return {
        "provider": "anthropic-compatible",
        "model": get_config().llm.model,
        "input_tokens": total_input,
        "output_tokens": output_tokens,
        "total_tokens": total_input + output_tokens,
    }


def complete_text(
    client: Anthropic,
    *,
    system: str,
    prompt: str,
    max_tokens: int,
) -> tuple[str, dict[str, Any]]:
    """Run one Anthropic-compatible completion with normalized text and usage."""
    response = client.messages.create(
        model=get_config().llm.model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "\n".join(block.text for block in response.content if hasattr(block, "text"))
    return text, extract_llm_usage(response)


def stream_text(
    client: Anthropic,
    *,
    system: str,
    prompt: str,
    max_tokens: int,
) -> Iterator[str]:
    """Yield text from one Anthropic-compatible streaming completion."""
    with client.messages.stream(
        model=get_config().llm.model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        yield from stream.text_stream
