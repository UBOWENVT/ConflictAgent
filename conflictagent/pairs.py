"""Shared extraction of judge inputs from a ConflictBench desirability label.

Single source of truth for turning a ManualLabel into the inputs a judge sees, so the hand-built
judge (scripts/calibrate_judge.py) and the DeepEval suite (evaluation/) see byte-identical inputs.

Mirrors the original calibrate_judge.build_pair: prefer real-file region extraction (same
git-block span on both sides), fall back to cleaned xlsx snippets when files are missing or anchors
aren't unique. Adds the conflict block itself (the diff3 being resolved), used as the GEval INPUT.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import data, groundtruth, merge, validate


@dataclass
class JudgeInputs:
    conflict: str      # the conflict block being resolved (diff3 markers) — GEval INPUT context
    candidate: str     # the resolution under test (a tool's or solver's output region)
    developer: str     # the developer's resolution of the same block (ground truth)
    source: str        # 'file' (real-file regions) or 'xlsx' (annotation-snippet fallback)


def build_judge_inputs(lab: data.ManualLabel) -> JudgeInputs:
    """Build (conflict, candidate, developer, source) for one desirability label.

    Candidate and developer always come from the SAME source so the pair is span-consistent
    (identical to the original build_pair). The conflict block is taken from the reconstructed
    merged file when available, else from the xlsx MERGED snippet.
    """
    files = data.load_scenario_files(lab.project, lab.commit)
    if {"base", "left", "right"} <= files.keys():
        merged, _ = merge.reconstruct_merged(files["base"], files["left"], files["right"])
        idx, _ = groundtruth.select_target_block(merged, lab.merged_snippet)
        tool_file = files.get(data.tool_folder(lab.tool))
        child_file = files.get("child")
        if idx >= 0 and tool_file is not None and child_file is not None:
            tool_region, st_t = groundtruth.resolution_region(tool_file, merged, idx)
            dev_region, st_d = groundtruth.resolution_region(child_file, merged, idx)
            if st_t == "ok" and st_d == "ok":
                blocks = validate.conflict_blocks(merged)
                conflict = blocks[idx] if 0 <= idx < len(blocks) else (lab.merged_snippet or "")
                return JudgeInputs(conflict, tool_region, dev_region, "file")
    # fallback: cleaned xlsx snippets (both sides at the human annotation span); the conflict is
    # the xlsx MERGED snippet (the annotated git-merge conflict chunk).
    return JudgeInputs(
        conflict=lab.merged_snippet or "",
        candidate=data.clean_xlsx_snippet(lab.tool_resolution),
        developer=data.clean_xlsx_snippet(lab.developer),
        source="xlsx",
    )


def build_pair(lab: data.ManualLabel) -> tuple[str, str, str]:
    """Back-compat shim used by scripts/calibrate_judge.py: (candidate, developer, source)."""
    ji = build_judge_inputs(lab)
    return ji.candidate, ji.developer, ji.source
