"""Thin multi-provider chat wrapper (OpenAI / Anthropic / Gemini).

Single entry point: `call(provider, model, system, user) -> str` so that
solver/judge code stays provider-agnostic. SDK imports are lazy (inside function
bodies) — the module itself imports without any SDK installed.

Wraps with tenacity retry (10 attempts, exponential backoff 5s->90s, ~5 min total,
each backoff logged) for transient server / rate-limit errors such as Gemini 503
"high demand" spikes. Key-validation errors are raised immediately in call() without retry.

Gemini uses the current `google-genai` SDK (`from google import genai`).
"""
from __future__ import annotations

import logging

from tenacity import (
    before_sleep_log,
    retry,
    stop_after_attempt,
    wait_exponential,
)

from . import config

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy-initialized clients (created on first call, not on import)
# ---------------------------------------------------------------------------
_openai_client = None
_gemini_client = None


def _get_openai():
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI  # lazy

        if not config.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY not set — fill in .env")
        _openai_client = OpenAI(api_key=config.OPENAI_API_KEY)
    return _openai_client


def _get_gemini():
    global _gemini_client
    if _gemini_client is None:
        from google import genai  # lazy (google-genai SDK)

        if not config.GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY not set — fill in .env")
        _gemini_client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _gemini_client


def _get_anthropic():
    import anthropic  # lazy

    if not config.ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not set — fill in .env")
    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def call(provider: str, model: str, system: str, user: str, **kwargs) -> str:
    """Send a system + user prompt to *model* on *provider*; return the text.

    Validates key existence immediately (no retry). The actual API call is
    retried on transient errors via `_call_api`. Decoding temperature defaults to
    config.LLM_TEMPERATURE and is routed to each SDK's correct slot; pass
    temperature=None to omit it entirely (some OpenAI models reject temperature=0).
    """
    kwargs.setdefault("temperature", config.LLM_TEMPERATURE)

    # Fail fast on missing keys (before any retry loop).
    if provider == "openai":
        _get_openai()
    elif provider == "anthropic":
        _get_anthropic()
    elif provider == "gemini":
        _get_gemini()
    else:
        raise ValueError(f"Unknown provider: {provider!r}")

    return _call_api(provider, model, system, user, **kwargs)


@retry(
    wait=wait_exponential(min=5, max=90),
    stop=stop_after_attempt(10),                          # ~5 min total backoff (5->90s) for 503 spikes
    before_sleep=before_sleep_log(log, logging.WARNING),  # log each backoff so spikes are visible
    reraise=True,
)
def _call_api(provider: str, model: str, system: str, user: str,
              temperature: float | None = None, **kwargs) -> str:
    """The actual SDK call, wrapped with tenacity for transient errors.

    `temperature` is routed to each SDK's correct location and omitted when None.
    """

    if provider == "openai":
        client = _get_openai()
        if temperature is not None:
            kwargs["temperature"] = temperature
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            **kwargs,
        )
        return resp.choices[0].message.content or ""

    elif provider == "anthropic":
        client = _get_anthropic()
        if temperature is not None:
            kwargs["temperature"] = temperature
        resp = client.messages.create(
            model=model,
            max_tokens=kwargs.pop("max_tokens", 4096),
            system=system,
            messages=[{"role": "user", "content": user}],
            **kwargs,
        )
        return resp.content[0].text

    elif provider == "gemini":
        from google.genai import types  # lazy

        client = _get_gemini()
        if temperature is not None:
            kwargs["temperature"] = temperature
        resp = client.models.generate_content(
            model=model,
            contents=user,
            config=types.GenerateContentConfig(system_instruction=system, **kwargs),
        )
        # resp.text raises / is None if the response was blocked by safety filters;
        # tenacity retries transient blocks, persistent ones surface after max attempts.
        return resp.text or ""

    # unreachable (call() already validated provider)
    raise ValueError(f"Unknown provider: {provider!r}")
