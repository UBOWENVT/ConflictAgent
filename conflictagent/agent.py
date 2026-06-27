"""The resolve-(or-punt) loop for one scenario (SPEC layer B — NO ground truth in the loop).

    merged, _ = merge.reconstruct_merged(base, left, right)   # full file, diff3 markers
    target    = groundtruth.select_target_block(merged, xlsx MERGED)   # the annotated block
    mark the target block; show the solver a WINDOW of the file (skeleton + enclosing scope)
    solver.solve(scheme) -> per scheme:
       scheme B, TRUE_CONFLICT -> punt (predicted true conflict); a Detection event; no validation
       otherwise              -> a resolution of the target block; validate + retry loop
    validate (no ground truth): the resolution is marker-free; for single-block files also
    splice + syntax-check the whole file. Multi-block files keep their other blocks, so a
    full parse isn't possible — a marker-free resolution is accepted.

Windowing affects only what the solver SEES; splicing/validation use the full reconstructed file,
so the window can never corrupt the resolution. The judge is NOT called here; desirability is
judged afterwards, outside the loop (run_eval).
"""
from __future__ import annotations

from . import config, groundtruth, merge, solver, validate
from .data import Scenario


def _annotate_target(merged: str, target_idx: int) -> str:
    """Tag the target conflict block's opening <<<<<<< line so the solver acts on that one."""
    spans = validate.block_spans(merged)
    s, e = spans[target_idx]
    block = merged[s:e]
    nl = block.find("\n")
    if nl == -1:
        tagged = block + "   " + solver.TARGET_TAG
    else:
        tagged = block[:nl] + "   " + solver.TARGET_TAG + block[nl:]
    return merged[:s] + tagged + merged[e:]


def _validate(resolution: str, merged: str, target_idx: int, is_java: bool) -> tuple[bool, str]:
    """Inference-time validation (no ground truth)."""
    if not resolution.strip():
        # An empty/whitespace-only resolution means the model returned no usable text (truncation,
        # safety block, or an empty completion). Without this guard it slips through: it has no
        # conflict markers, and for multi-block files (or files that still parse with the block
        # deleted) the checks below would wrongly accept it. Fail it so the loop retries.
        return False, "Empty resolution \u2014 the model returned no text. Output the replacement for the tagged <<<<<<< \u2026 >>>>>>> region."
    if validate.has_conflict_markers(resolution):
        return False, "Output still contained conflict markers (<<<<<<< / ======= / >>>>>>>)."
    spliced = validate.splice_block(merged, resolution, target_idx)
    if validate.has_conflict_markers(spliced):
        return True, ""          # other blocks remain (multi-block) — can't full-parse; resolution is clean
    if is_java:
        ok, err = validate.syntax_valid(spliced)
        if not ok:
            return False, err
        dup, what = validate.has_duplicate_declarations(spliced)
        if dup:
            return False, (
                f"Your output included code from OUTSIDE the conflict region ({what}). "
                f"Output ONLY the replacement for the tagged <<<<<<< … >>>>>>> region — "
                f"nothing before the <<<<<<< line or after the >>>>>>> line."
            )
        return True, ""
    return True, ""              # non-Java: marker-free is the best signal we have


def resolve(provider: str, s: Scenario, full_versions: dict[str, str],
            scheme: str = config.DEFAULT_SCHEME) -> dict:
    """Run the resolve-(or-punt) loop for one scenario under the given scheme.

    Returns a record with the scheme, verdict, self-reported strategy/confidence, per-round
    candidates, and the finalized resolution (target block only).
    """
    merged, had_conflict = merge.reconstruct_merged(
        full_versions["base"], full_versions["left"], full_versions["right"]
    )
    blocks = validate.conflict_blocks(merged)
    base_record = {
        "id": s.id, "project": s.project, "commit": s.commit,
        "file_type": s.file_type, "valid_conflict": s.valid_conflict,
        "provider": provider, "scheme": scheme,
        "had_conflict": had_conflict, "n_blocks": len(blocks),
    }
    if len(blocks) == 0:
        return {**base_record, "status": "no_conflict", "target_idx": -1, "rounds": []}

    target_idx, overlap = groundtruth.select_target_block(merged, s.conflict_chunk)
    if target_idx < 0:
        return {**base_record, "status": "no_conflict", "target_idx": -1, "rounds": []}
    base_record["target_idx"] = target_idx
    base_record["target_overlap"] = round(overlap, 3)

    marked = _annotate_target(merged, target_idx)
    window = solver.build_window(marked, target_idx)

    rounds: list[dict] = []
    prior_attempt: str | None = None
    validator_error: str | None = None
    last: dict = {}

    for r in range(config.MAX_RETRIES + 1):          # round 0 = first attempt, then retries
        out = solver.solve(provider, scheme, window, prior_attempt, validator_error)
        last = out
        if out["conflict_type"] == "true_conflict":   # only reachable in scheme B
            return {**base_record, "status": "punt", "predicted_true_conflict": True,
                    "reasoning": out["reasoning"], "strategy": out["strategy"],
                    "confidence": out["confidence"],
                    "rounds": rounds, "n_rounds": len(rounds) + 1}
        resolution = out["resolution"]
        valid, err = _validate(resolution, merged, target_idx, s.is_java)
        rounds.append({"round": r, "resolution": resolution, "valid": valid, "error": err,
                       "strategy": out["strategy"], "confidence": out["confidence"]})
        if valid:
            break
        prior_attempt, validator_error = resolution, err

    final = rounds[-1]
    # If retries were exhausted and the model still produced nothing usable, this is NOT a
    # resolution -- mark it 'empty' so it is never counted as resolved or judged as a wrong answer
    # (an empty output is a non-result, not an unacceptable resolution).
    produced = bool(final["resolution"].strip())
    return {
        **base_record,
        "status": "resolved" if produced else "empty",
        "predicted_true_conflict": False,
        "reasoning": last.get("reasoning", ""),
        "strategy": final["strategy"],
        "confidence": final["confidence"],
        "rounds": rounds,
        "n_rounds": len(rounds),
        "final_resolution": final["resolution"],
        "final_valid": final["valid"],
    }
