"""Offline LLM-as-judge (SPEC architecture layer A — uses ground truth, OUTSIDE the loop).

Compares {candidate resolution, developer version} and reports semantic equivalence.
Uses config.JUDGE_MODEL — a different vendor from the solvers, to avoid self-preference.

Trust requires calibration: before using the judge for headline numbers, run it on
ConflictBench's ~627 manual desirability labels and measure agreement (see
scripts/calibrate_judge.py). Report that agreement rate alongside results.
"""
from __future__ import annotations


def judge_equivalent(candidate: str, developer: str) -> dict:
    """Return {'equivalent': bool, 'reason': str} for one (candidate, developer) pair.

    TODO: llm.call(*JUDGE_MODEL, system=judge_rubric, user=both versions); parse
    a structured yes/no + short reason. Keep the rubric tight (semantic, not textual,
    equivalence) and the output schema machine-parseable.
    """
    raise NotImplementedError
