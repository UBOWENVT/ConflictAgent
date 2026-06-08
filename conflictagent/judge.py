"""Offline LLM-as-judge (SPEC architecture layer A — uses ground truth, OUTSIDE the loop).

Judges whether a candidate resolution is an ACCEPTABLE resolution of a merge conflict relative to
the developer's actual resolution — i.e. it captures the developer's merge intent and behavior,
even if not character-identical. This deliberately targets the human "desirability" notion, NOT
strict character/AST equivalence: calibration (scripts/calibrate_judge.py) against ConflictBench's
~627 manual desirability labels showed that a strict-equivalence rubric tanks recall (it flags
acceptable import-subset / reordering differences as failures), so the rubric below tolerates
housekeeping differences while still rejecting unresolved output and real logic/value differences.

Uses config.JUDGE_MODEL — a different vendor from the solvers (avoid self-preference).
The return key is 'equivalent' (bool) for pipeline compatibility; it now means "acceptable".
"""
from __future__ import annotations

from . import config, llm

JUDGE_SYSTEM = (
    "You are reviewing a resolved Git merge conflict. You are given a CANDIDATE resolution and the "
    "DEVELOPER's actual resolution of the SAME conflict. Decide whether the candidate is an "
    "ACCEPTABLE resolution: would a careful reviewer accept it as resolving the conflict the way the "
    "developer intended — same behavior and same essential content — even if not character-identical?"
    "\n\nACCEPT (these alone do NOT make it unacceptable):\n"
    "- whitespace, indentation, formatting, or comments;\n"
    "- ordering of imports, fields, or methods;\n"
    "- a different but behaviorally equivalent phrasing of the same logic;\n"
    "- a different set of import statements (which imports are present is housekeeping, not logic), "
    "as long as the actual code is consistent.\n\n"
    "REJECT as NOT_ACCEPTABLE:\n"
    "- the candidate still contains conflict markers (<<<<<<<, =======, >>>>>>>) or is otherwise an "
    "unresolved / partial merge — failing to resolve is never acceptable;\n"
    "- different program logic or behavior;\n"
    "- different literal values that matter (version numbers, constants, configuration values);\n"
    "- missing or extra FUNCTIONAL code (statements, methods, conditions — not imports);\n"
    "- choosing a different side's behavior than the developer did.\n\n"
    "Output exactly two lines and nothing else:\n"
    "VERDICT: ACCEPTABLE or NOT_ACCEPTABLE\n"
    "REASON: <one short sentence>"
)


def _parse(text: str) -> tuple[bool | None, str]:
    """Return (acceptable, reason). acceptable is None if the verdict can't be parsed.

    Order matters: 'NOT_ACCEPTABLE' contains 'ACCEPTABLE', so test the negative first.
    """
    acceptable: bool | None = None
    reason = ""
    for line in (text or "").splitlines():
        lu = line.upper()
        if acceptable is None and "VERDICT" in lu:
            if "NOT_ACCEPTABLE" in lu or "NOT ACCEPTABLE" in lu:
                acceptable = False
            elif "ACCEPTABLE" in lu:
                acceptable = True
        elif lu.startswith("REASON"):
            reason = line.split(":", 1)[-1].strip()
    if acceptable is None:  # fallback: scan whole text
        up = (text or "").upper()
        if "NOT_ACCEPTABLE" in up or "NOT ACCEPTABLE" in up:
            acceptable = False
        elif "ACCEPTABLE" in up:
            acceptable = True
    return acceptable, reason


def judge_equivalent(candidate: str, developer: str) -> dict:
    """Return {'equivalent': bool|None, 'reason': str, 'raw': str} for one pair.

    'equivalent' means "acceptable per the rubric" (kept under this key for pipeline compatibility).
    """
    provider, model = config.JUDGE_MODEL
    user = (
        "## Candidate resolution:\n" + (candidate or "(empty)") +
        "\n\n## Developer's resolution:\n" + (developer or "(empty)")
    )
    raw = llm.call(provider, model, JUDGE_SYSTEM, user)
    acceptable, reason = _parse(raw)
    return {"equivalent": acceptable, "reason": reason, "raw": raw}


# --------------------------------------------------------------------------- #
# Standalone-valid judge: is the resolution sensible on its own, WITHOUT the developer answer?
# --------------------------------------------------------------------------- #
# This is the second desirability notion (2026-06-08 redirect): does the candidate look like a
# reasonable resolution given only base/left/right? The gap between this and developer-match is
# "resolved correctly, but differently from the developer" — exactly where a semantic judge beats
# exact-match. This judge never sees the developer's answer.

STANDALONE_SYSTEM = (
    "You are reviewing a proposed resolution of a Git merge conflict. You are given the conflict in "
    "diff3 form (BASE = common ancestor, LEFT = one side's change, RIGHT = the other side's change) "
    "and a CANDIDATE resolution. There is NO reference answer. Decide whether the candidate is a "
    "reasonable, self-consistent resolution that an experienced engineer could accept: it should "
    "honor the apparent intent of BOTH sides' changes where they are compatible, not silently drop "
    "a side's functional change without cause, and be syntactically plausible.\n\n"
    "ACCEPT if the candidate is a coherent merge of the two changes (or a justified choice of one "
    "side when the sides are mutually exclusive). Housekeeping differences (whitespace, import set, "
    "ordering, comments) never make it unacceptable.\n\n"
    "REJECT as NOT_ACCEPTABLE if the candidate: still contains conflict markers or is a partial/"
    "unresolved merge; drops a side's functional change for no defensible reason; introduces logic "
    "absent from both sides; or is syntactically broken.\n\n"
    "Output exactly two lines and nothing else:\n"
    "VERDICT: ACCEPTABLE or NOT_ACCEPTABLE\n"
    "REASON: <one short sentence>"
)


def judge_standalone(candidate: str, left: str, base: str, right: str) -> dict:
    """Judge a candidate resolution against the conflict itself (no developer answer).

    Return {'equivalent': bool|None, 'reason': str, 'raw': str} — same key as judge_equivalent
    ('equivalent' == 'standalone-acceptable') so callers share plumbing.
    """
    provider, model = config.JUDGE_MODEL
    user = (
        "## Conflict (diff3):\n"
        "<<<<<<< LEFT\n" + (left or "(empty)") +
        "\n||||||| BASE\n" + (base or "(empty)") +
        "\n=======\n" + (right or "(empty)") +
        "\n>>>>>>> RIGHT\n\n## Candidate resolution:\n" + (candidate or "(empty)")
    )
    raw = llm.call(provider, model, STANDALONE_SYSTEM, user)
    acceptable, reason = _parse(raw)
    return {"equivalent": acceptable, "reason": reason, "raw": raw}
