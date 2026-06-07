"""Thin multi-provider chat wrapper (OpenAI / Anthropic / Gemini).

Goal: one `call(provider, model, system, user)` entry point so solver/judge code
stays provider-agnostic. Implement each provider branch below and wrap with
tenacity retry/backoff for rate limits and transient errors.
"""
from __future__ import annotations


def call(provider: str, model: str, system: str, user: str, **kwargs) -> str:
    """Send a system+user prompt to `model` on `provider`; return the text response.

    TODO: implement per-provider branches.
      - openai:    client.chat.completions.create(model=, messages=[system, user])
      - anthropic: client.messages.create(model=, system=, messages=[user])
      - gemini:    client.models.generate_content(model=, contents=, system_instruction=)
    Centralize key lookup via config.{OPENAI,GEMINI,ANTHROPIC}_API_KEY.
    Add @tenacity.retry(...) for 429 / 5xx backoff.
    """
    raise NotImplementedError("llm.call: implement provider branches")
