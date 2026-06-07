"""Extract the developer's resolution of a conflict block from the child FILE.

SPEC architecture layer A (uses ground truth) — runs OUTSIDE the agent loop, only for judging.

Why from the child file (not the xlsx CHILD snippet): the xlsx snippet is a unified-diff
annotation at a human-chosen (wider) span and in diff format; the child file is the developer's
exact final code. We locate the developer's resolution of a specific git conflict block by using
the context lines bracketing that block as anchors and finding them in the child file.

Safety: a uniqueness guard. If the anchors don't match EXACTLY ONCE in the child file, extraction
is unsafe (could silently land in the wrong place), so we return a status flag instead of a guess.

Validated on ConflictBench 2026-06-07 (93 Java scenarios): among locatable scenarios, extraction
agrees with the original manual annotations in ~97% of cases (content-consistent); the guard
excludes ~23% as unsafe, and a separate cross-check flags ~2 "developer rewrote the region" cases.
The ground-truth block is consistently block #0 (matches the human MERGED annotation).
"""
from __future__ import annotations

from . import validate

_ANCHOR_K = (3, 4, 5)  # try progressively larger context windows to get a unique match


def is_balanced(code: str) -> bool:
    """Cheap structural sanity check: braces and parens balance. An unbalanced extracted
    region usually means git cut the conflict boundary across a structural unit."""
    return code.count("{") == code.count("}") and code.count("(") == code.count(")")


def developer_region(child_text: str, merged_text: str, block_index: int = 0) -> tuple[str | None, str]:
    """Return (region_text, status).

    status:
      'ok'                -> region_text is the developer's resolution of the chosen block
      'no_block'          -> the merged file has no such conflict block
      'anchor_not_unique' -> context anchors not found exactly once in child (unsafe; excluded)
    """
    blocks = validate.conflict_blocks(merged_text)
    if not blocks or block_index >= len(blocks):
        return None, "no_block"

    mlines = merged_text.splitlines()
    starts = [i for i, l in enumerate(mlines) if l.startswith("<<<<<<<")]
    ends = [i for i, l in enumerate(mlines) if l.startswith(">>>>>>>")]
    si, ei = starts[block_index], ends[block_index]
    cl = child_text.splitlines()

    for k in _ANCHOR_K:
        before, after = mlines[si - k:si], mlines[ei + 1:ei + 1 + k]
        if len(before) < k or len(after) < k:
            continue
        bi = [i for i in range(len(cl) - k + 1) if cl[i:i + k] == before]
        if len(bi) != 1:
            continue
        start = bi[0] + k
        ai = [j for j in range(start, len(cl) - k + 1) if cl[j:j + k] == after]
        if len(ai) != 1:
            continue
        return "\n".join(cl[start:ai[0]]), "ok"

    return None, "anchor_not_unique"
