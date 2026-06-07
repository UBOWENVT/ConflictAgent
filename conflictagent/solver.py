"""Solver: build the prompt and call a solver LLM for one conflict.

Starts from the baseline's two-stage prompt (classify valid/true conflict, then
resolve if resolvable, choosing among the 7 strategies) but is structured for the
agent loop: on a retry, the previous candidate + the validator's error are appended.

Input granularity follows config.INPUT_GRANULARITY (start = 'region': the two diffs
+ conflict chunk, ~300 tokens; 'window' / 'file' are fallbacks for more context).
"""
from __future__ import annotations

from .data import Scenario


def build_prompt(s: Scenario, prior_attempt: str | None = None,
                 validator_error: str | None = None) -> tuple[str, str]:
    """Return (system, user) prompt. On retries, fold in prior_attempt + validator_error.

    TODO: port the two-stage system prompt from the baseline (Valid Conflict TRUE/FALSE
    then resolution + strategy + reason), keeping the 5-field output schema.
    """
    raise NotImplementedError


def solve(provider: str, s: Scenario, prior_attempt: str | None = None,
          validator_error: str | None = None) -> dict:
    """Call the solver, parse the 5-field structured output into a dict.

    TODO: llm.call(provider, SOLVER_MODELS[provider], system, user) -> parse
    (valid_conflict, check_reason, strategy, resolution_content, reason).
    Be robust to parse failures (the baseline had a parse bug — don't repeat it).
    """
    raise NotImplementedError
