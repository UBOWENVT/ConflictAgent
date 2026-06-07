"""The validate-and-repair loop (SPEC architecture layer B — no ground truth).

    round 0: solver.solve(...)                      # == single-shot baseline
    validate (syntax + conflict markers)
    while invalid and round < MAX_RETRIES:
        round += 1
        solver.solve(..., prior_attempt, validator_error)   # feed error back
        validate
    finalize

Record the candidate at EVERY round so metrics.py can show how syntax-valid rate /
desirability improve per retry round (round 0 = baseline). The judge is NOT called
here — it runs afterwards, outside the loop.
"""
from __future__ import annotations

from .data import Scenario


def resolve(provider: str, s: Scenario) -> dict:
    """Run the loop for one scenario; return a record with per-round candidates,
    validity, final resolution, and round count.

    TODO: implement the generate->validate->retry loop described above using
    solver.solve + validate.{splice_resolution, syntax_valid, has_conflict_markers}.
    """
    raise NotImplementedError
