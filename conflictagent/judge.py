"""Offline LLM-as-judge (SPEC architecture layer A — uses ground truth, OUTSIDE the loop).

Judges whether a candidate resolution is SEMANTICALLY EQUIVALENT to the developer's actual
resolution. Uses config.JUDGE_MODEL — a different vendor from the solvers (avoid self-preference).

Before trusting the judge for headline numbers, calibrate it against ConflictBench's ~627 manual
desirability labels (scripts/calibrate_judge.py) and report the agreement rate.
"""
from __future__ import annotations

from . import config, llm

JUDGE_SYSTEM = (
    "You are evaluating a resolved Git merge conflict. You are given a CANDIDATE resolution and "
    "the DEVELOPER's actual resolution for the same conflict. Decide whether the candidate is "
    "SEMANTICALLY EQUIVALENT to the developer's resolution: would they behave the same way and "
    "express the same intent?\n\n"
    "- Ignore differences in whitespace, indentation, formatting, comments, and trivial reordering.\n"
    "- Treat as NOT equivalent any real difference: different logic or values, missing or extra "
    "code, a different choice between the two sides.\n\n"
    "Output exactly two lines and nothing else:\n"
    "VERDICT: EQUIVALENT or NOT_EQUIVALENT\n"
    "REASON: <one short sentence>"
)


def _parse(text: str) -> tuple[bool | None, str]:
    """Return (equivalent, reason). equivalent is None if the verdict can't be parsed."""
    equivalent: bool | None = None
    reason = ""
    for line in (text or "").splitlines():
        lu = line.upper()
        if equivalent is None and "VERDICT" in lu:
            if "NOT_EQUIVALENT" in lu or "NOT EQUIVALENT" in lu:
                equivalent = False
            elif "EQUIVALENT" in lu:
                equivalent = True
        elif line.upper().startswith("REASON"):
            reason = line.split(":", 1)[-1].strip()
    if equivalent is None:  # fallback: scan whole text
        up = (text or "").upper()
        if "NOT_EQUIVALENT" in up or "NOT EQUIVALENT" in up:
            equivalent = False
        elif "EQUIVALENT" in up:
            equivalent = True
    return equivalent, reason


def judge_equivalent(candidate: str, developer: str) -> dict:
    """Return {'equivalent': bool|None, 'reason': str, 'raw': str} for one pair."""
    provider, model = config.JUDGE_MODEL
    user = (
        "## Candidate resolution:\n" + (candidate or "(empty)") +
        "\n\n## Developer's resolution:\n" + (developer or "(empty)")
    )
    raw = llm.call(provider, model, JUDGE_SYSTEM, user)
    equivalent, reason = _parse(raw)
    return {"equivalent": equivalent, "reason": reason, "raw": raw}
