"""The three metrics (SPEC; aligned with the resume), reported per retry round.

  1. syntax_valid_rate  -- fraction parsing as valid Java. Denominator = Java subset (106).
  2. token_level_f1     -- vs developer version; cheap lexical overlap, no judge needed.
  3. judge_equivalence  -- vs developer version; needs the calibrated judge.

Core deliverable = single-shot baseline (round 0) vs agent-loop delta across rounds.
Keep all numbers grounded in actual runs — never hard-code example results here.
"""
from __future__ import annotations


def syntax_valid_rate(records: list[dict]) -> float:
    """Fraction of Java scenarios whose final resolution parses. TODO."""
    raise NotImplementedError


def token_level_f1(candidate: str, developer: str) -> float:
    """Token-level F1 between candidate and developer version. TODO (tokenize, P/R/F1)."""
    raise NotImplementedError


def judge_equivalence_rate(records: list[dict]) -> float:
    """Fraction judged semantically equivalent to the developer version. TODO."""
    raise NotImplementedError
