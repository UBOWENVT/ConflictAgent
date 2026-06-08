"""Extract a resolution region from a fully-resolved FILE, and pick the annotated block.

SPEC architecture layer A (uses ground truth) — runs OUTSIDE the agent loop, only for judging.

We work from the real resolved files (child/ for the developer; {Tool}/ for each merge tool),
NOT the xlsx diff snippets. A resolution's region for a specific git conflict block is located by
using the context lines bracketing that block (in the reconstructed merged file) as anchors and
finding them in the resolved file.

Two safety / correctness aids, both cross-checked against the human xlsx annotation:
  - select_target_block(): the annotated block is usually block #0 but not always (~<10%); pick the
    block whose content best matches the xlsx MERGED snippet instead of blindly taking #0.
  - uniqueness guard in resolution_region(): if the anchors don't match exactly once, return a
    status flag instead of a possibly-wrong region.

Validated on ConflictBench 2026-06-07 (93 Java): among locatable scenarios extraction agrees with
the manual annotations in ~97% of cases; the guard excludes ~23% as unsafe; a cross-check flags a
couple "developer rewrote the region" cases.
"""
from __future__ import annotations

from . import validate

_ANCHOR_K = (3, 4, 5)  # try progressively larger context windows to get a unique match


def is_balanced(code: str) -> bool:
    """Cheap structural sanity check: braces and parens balance. An unbalanced extracted
    region usually means git cut the conflict boundary across a structural unit."""
    return code.count("{") == code.count("}") and code.count("(") == code.count(")")


def _content_lines(block_or_snippet: str) -> set[str]:
    """Stripped, non-empty content lines, ignoring conflict markers (used for block matching)."""
    out = set()
    for l in (block_or_snippet or "").splitlines():
        if l.startswith(("<<<<<<<", "|||||||", "=======", ">>>>>>>")):
            continue
        s = l.strip()
        if s:
            out.add(s)
    return out


def select_target_block(merged_text: str, xlsx_merged_snippet: str | None) -> tuple[int, float]:
    """Pick the conflict block that matches the human-annotated xlsx MERGED snippet.

    Returns (block_index, overlap_fraction). overlap_fraction is the share of the xlsx snippet's
    content lines found in the chosen block (1.0 = full). Falls back to (0, 0.0) when there is no
    xlsx snippet to match against, and (-1, 0.0) when the merged file has no conflict block.
    """
    blocks = validate.conflict_blocks(merged_text)
    if not blocks:
        return -1, 0.0
    target = _content_lines(xlsx_merged_snippet) if xlsx_merged_snippet else set()
    if not target:
        return 0, 0.0
    best_i, best_ov = 0, 0.0
    for i, b in enumerate(blocks):
        bl = _content_lines(b)
        if not bl:
            continue
        ov = len(target & bl) / len(target)
        if ov > best_ov:
            best_ov, best_i = ov, i
    return best_i, best_ov


def resolution_region(resolved_text: str, merged_text: str, block_index: int = 0) -> tuple[str | None, str]:
    """Locate the resolution of conflict block `block_index` inside a fully-resolved file.

    Works for any resolved file (child = developer, or a {Tool}/ output). Return (region_text, status):
      'ok'                -> region_text is that file's resolution of the chosen block
      'no_block'          -> the merged file has no such conflict block
      'anchor_not_unique' -> context anchors not found exactly once in the resolved file (unsafe)
    """
    blocks = validate.conflict_blocks(merged_text)
    if not blocks or block_index >= len(blocks):
        return None, "no_block"

    mlines = merged_text.splitlines()
    starts = [i for i, l in enumerate(mlines) if l.startswith("<<<<<<<")]
    ends = [i for i, l in enumerate(mlines) if l.startswith(">>>>>>>")]
    si, ei = starts[block_index], ends[block_index]
    rl = resolved_text.splitlines()

    for k in _ANCHOR_K:
        before, after = mlines[si - k:si], mlines[ei + 1:ei + 1 + k]
        if len(before) < k or len(after) < k:
            continue
        bi = [i for i in range(len(rl) - k + 1) if rl[i:i + k] == before]
        if len(bi) != 1:
            continue
        start = bi[0] + k
        ai = [j for j in range(start, len(rl) - k + 1) if rl[j:j + k] == after]
        if len(ai) != 1:
            continue
        return "\n".join(rl[start:ai[0]]), "ok"

    return None, "anchor_not_unique"


def developer_region(child_text: str, merged_text: str, block_index: int = 0) -> tuple[str | None, str]:
    """Developer's resolution of a block (thin alias over resolution_region on the child file)."""
    return resolution_region(child_text, merged_text, block_index)
