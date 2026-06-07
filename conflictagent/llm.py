"""Thin multi-provider chat wrapper (OpenAI / Anthropic / Gemini).

Single entry point: `call(provider, model, system, user) -> str` so that
solver/judge code stays provider-agnostic. SDK imports are lazy (inside function
bodies) — the module itself imports without any SDK installed.

Wraps with tenacity retry for transient / rate-limit errors. Key-validation
errors are raised immediately without retry.
"""
from __future__ import annotations

import logging

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
)

from . import config

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy-initialized state (created on first call, not on import)
# ---------------------------------------------------------------------------
_openai_client = None
_gemini_configured = False


def _get_openai():
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI  # lazy

        if not config.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY not set — fill in .env")
        _openai_client = OpenAI(api_key=config.OPENAI_API_KEY)
    return _openai_client


def _ensure_gemini():
    global _gemini_configured
    if not _gemini_configured:
        import google.generativeai as genai  # lazy

        if not config.GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY not set — fill in .env")
        genai.configure(api_key=config.GEMINI_API_KEY)
        _gemini_configured = True


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
    retried on transient errors via `_call_api`.

    Parameters
    ----------
    provider : 'openai' | 'anthropic' | 'gemini'
    model    : API model-id string (see config.SOLVER_MODELS / JUDGE_MODEL)
    system   : system-prompt text
    user     : user-prompt text
    **kwargs : passed through to the provider SDK call
    """
    # Fail fast on missing keys (before any retry loop).
    if provider == "openai":
        _get_openai()          # raises ValueError if key missing
    elif provider == "anthropic":
        _get_anthropic()
    elif provider == "gemini":
        _ensure_gemini()
    else:
        raise ValueError(f"Unknown provider: {provider!r}")

    return _call_api(provider, model, system, user, **kwargs)


@retry(
    wait=wait_exponential(min=2, max=60),
    stop=stop_after_attempt(5),
    reraise=True,
)
def _call_api(provider: str, model: str, system: str, user: str, **kwargs) -> str:
    """The actual SDK call, wrapped with tenacity for transient errors."""

    if provider == "openai":
        client = _get_openai()
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
        resp = client.messages.create(
            model=model,
            max_tokens=kwargs.pop("max_tokens", 4096),
            system=system,
            messages=[{"role": "user", "content": user}],
            **kwargs,
        )
        return resp.content[0].text

    elif provider == "gemini":
        import google.generativeai as genai

        gm = genai.GenerativeModel(model_name=model, system_instruction=system)
        resp = gm.generate_content(user)
        # resp.text raises if the response was blocked by safety filters.
        # Let tenacity retry handle transient blocks; persistent blocks will
        # surface after max attempts.
        return resp.text

    # unreachable (call() already validated provider)
    raise ValueError(f"Unknown provider: {provider!r}")
