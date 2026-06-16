"""Small metric helpers kept for ad hoc analysis.

The original metrics module described the old headline metrics: retry-round syntax-valid rate,
token-level F1, and single-shot-vs-loop delta. Those are no longer the project's primary metrics.

Current primary metrics are computed directly in scripts/run_eval.py and scripts/compare_tools.py:

- developer-match, judged by the calibrated judge;
- standalone-valid, used substantively only on false conflicts;
- scheme-B detection precision/recall;
- confidence calibration;
- trivial baseline rates.
"""

from __future__ import annotations


def rate(numerator: int, denominator: int) -> float:
    """Return numerator / denominator, or 0.0 for an empty denominator."""
    return numerator / denominator if denominator else 0.0


def format_rate(numerator: int, denominator: int) -> str:
    """Format a count and percentage consistently for summaries."""
    return f"{numerator}/{denominator} = {rate(numerator, denominator):.1%}"
