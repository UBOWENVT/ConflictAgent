"""The validate-and-repair loop (SPEC architecture layer B — NO ground truth).

For one scenario:
    merged, _ = merge.reconstruct_merged(base, left, right)   # diff3, with markers
    region    = the single conflict block
    round 0:  solver.solve(region)                            # == single-shot baseline
    validate: splice candidate back into merged -> syntax (Java) + leftover-marker check
    while invalid and round < MAX_RETRIES:
        round += 1
        solver.solve(region, prior_attempt, validator_error)  # feed the error back
        validate
    finalize

The candidate at EVERY round is recorded so metrics can show improvement per retry round
(round 0 = the loop-off baseline). The judge is NOT called here — it runs afterwards,
outside the loop (see judge.py). Multi-block conflicts are flagged, not resolved (MVP).
"""
from __future__ import annotations

from . import config, merge, solver, validate
from .data import Scenario


def _validate(spliced: str, is_java: bool) -> tuple[bool, str]:
    """Return (valid, error) using only inference-time signals (no ground truth)."""
    if validate.has_conflict_markers(spliced):
        return False, "Output still contained conflict markers (<<<<<<< / ======= / >>>>>>>)."
    if is_java:
        ok, err = validate.syntax_valid(spliced)
        return ok, err
    return True, ""          # non-Java: marker-free is the best signal we have


def resolve(provider: str, s: Scenario, full_versions: dict[str, str]) -> dict:
    """Run the loop for one scenario. `full_versions` = data.load_full_versions(s).

    Returns a record with per-round candidates + validity and the finalized resolution.
    """
    merged, had_conflict = merge.reconstruct_merged(
        full_versions["base"], full_versions["left"], full_versions["right"]
    )
    blocks = validate.conflict_blocks(merged)
    base_record = {
        "id": s.id, "project": s.project, "commit": s.commit,
        "file_type": s.file_type, "valid_conflict": s.valid_conflict,
        "provider": provider, "had_conflict": had_conflict, "n_blocks": len(blocks),
    }
    if len(blocks) == 0:
        return {**base_record, "status": "no_conflict", "rounds": []}
    if len(blocks) > 1:
        return {**base_record, "status": "multi_block_unsupported", "rounds": []}

    region = blocks[0]
    rounds: list[dict] = []
    prior_attempt: str | None = None
    validator_error: str | None = None

    for r in range(config.MAX_RETRIES + 1):          # round 0 = baseline, then retries
        out = solver.solve(provider, region, prior_attempt, validator_error)
        resolution = out["resolution"]
        spliced = validate.splice_resolution(merged, resolution)
        valid, err = _validate(spliced, s.is_java)
        rounds.append({"round": r, "resolution": resolution, "valid": valid, "error": err})
        if valid:
            break
        prior_attempt, validator_error = resolution, err

    final = rounds[-1]
    return {
        **base_record,
        "status": "ok",
        "rounds": rounds,
        "n_rounds": len(rounds),
        "final_resolution": final["resolution"],
        "final_valid": final["valid"],
    }
