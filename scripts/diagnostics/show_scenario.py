"""Visualize one scenario: what each version changed, where the conflict is, and
why developer-region anchors fail.

Three sections:
  (1) unified diffs base->left, base->right, base->child (what each side did)
  (2) the reconstructed merged conflict block(s), with line positions
  (3) the before/after anchors for the target block and their match positions in
      `child` -- showing exactly why a unique anchor pair cannot be found, plus
      the child region around the unique side so you can see what replaced the
      vanished anchor.

Run:
    python scripts/diagnostics/show_scenario.py Terasology@f9957aa0
    python scripts/diagnostics/show_scenario.py LoganSquare@a928069d --stdout

By default writes outputs/diagnostics/scenario_<project>_<short>.txt (gitignored).
"""
from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from conflictagent import config, data, merge, groundtruth, validate  # noqa: E402

_ANCHOR_K = (3, 4, 5)
_DIFF_CAP = 160  # max diff lines printed per version pair


def _udiff(a: str, b: str, label_a: str, label_b: str) -> list[str]:
    out = list(difflib.unified_diff(a.splitlines(), b.splitlines(),
                                    fromfile=label_a, tofile=label_b, lineterm="", n=2))
    if len(out) > _DIFF_CAP:
        out = out[:_DIFF_CAP] + [f"... ({len(out) - _DIFF_CAP} more diff lines truncated)"]
    return out or ["(no differences)"]


def _find(needle: list[str], hay: list[str]) -> list[int]:
    """1-based line numbers where the k-line `needle` window starts in `hay`."""
    k = len(needle)
    return [i + 1 for i in range(len(hay) - k + 1) if hay[i:i + k] == needle]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario", help="project@shortcommit, e.g. Terasology@f9957aa0")
    ap.add_argument("--stdout", action="store_true", help="print instead of writing a file")
    args = ap.parse_args()

    proj, short = args.scenario.split("@")
    s = next((x for x in data.load_scenarios()
              if x.project == proj and x.commit.startswith(short)), None)
    if s is None:
        sys.exit(f"scenario not found: {args.scenario}")
    fv = data.load_full_versions(s)
    if fv is None:
        sys.exit("base/left/right not on disk -> run scripts/fetch_data.py")

    base, left, right, child = fv["base"], fv["left"], fv["right"], fv["child"]
    merged, had = merge.reconstruct_merged(base, left, right)
    blocks = validate.conflict_blocks(merged)
    bi, ov = groundtruth.select_target_block(merged, s.conflict_chunk)

    mlines = merged.splitlines()
    starts = [i for i, l in enumerate(mlines) if l.startswith("<<<<<<<")]
    ends = [i for i, l in enumerate(mlines) if l.startswith(">>>>>>>")]
    rl = child.splitlines()

    L = []
    L.append(f"SCENARIO {args.scenario}")
    L.append(f"file           : {s.file_name}")
    L.append(f"valid_conflict : {s.valid_conflict}")
    L.append(f"had_conflict   : {had} | conflict blocks: {len(blocks)} | target block #{bi} "
             f"(xlsx overlap {ov:.2f})")
    L.append(f"sizes (lines)  : base={len(base.splitlines())} left={len(left.splitlines())} "
             f"right={len(right.splitlines())} child={len(child.splitlines())} merged={len(mlines)}")

    L.append("\n" + "=" * 70)
    L.append("(1) WHAT EACH VERSION CHANGED  (unified diff vs base, 2 lines context)")
    L.append("=" * 70)
    for lbl, txt in (("left", left), ("right", right), ("child (developer)", child)):
        L.append(f"\n----- base -> {lbl} -----")
        L.extend(_udiff(base, txt, "base", lbl))

    L.append("\n" + "=" * 70)
    L.append("(2) TARGET CONFLICT BLOCK  (in reconstructed merged)")
    L.append("=" * 70)
    if starts and bi < len(starts):
        si, ei = starts[bi], ends[bi]
        L.append(f"merged lines {si + 1}..{ei + 1} (file has {len(mlines)} lines):\n")
        L.extend(mlines[si:ei + 1])
    else:
        L.append("(no conflict block found)")

    L.append("\n" + "=" * 70)
    L.append("(3) WHY ANCHORS FAIL  (search before/after anchors in child)")
    L.append("=" * 70)
    if starts and bi < len(starts):
        si, ei = starts[bi], ends[bi]
        L.append(f"target block: merged lines [{si + 1}, {ei + 1}]; "
                 f"at_file_start={si < max(_ANCHOR_K)} at_file_end={(len(mlines) - 1 - ei) < max(_ANCHOR_K)}")
        for k in _ANCHOR_K:
            before = mlines[si - k:si] if si - k >= 0 else mlines[:si]
            after = mlines[ei + 1:ei + 1 + k]
            L.append(f"\n--- k={k} ---")
            if len(before) < k or len(after) < k:
                L.append(f"  EDGE: before has {len(before)} lines, after has {len(after)} "
                         f"(need {k}) -> anchor on the short side cannot be formed")
            bhits = _find(before, rl) if len(before) == k else []
            ahits = _find(after, rl) if len(after) == k else []
            L.append(f"  before anchor ({len(before)} lines), matches in child at {bhits or 'NONE'}:")
            for ln in before:
                L.append(f"      | {ln}")
            L.append(f"  after  anchor ({len(after)} lines), matches in child at {ahits or 'NONE'}:")
            for ln in after:
                L.append(f"      | {ln}")
            # if before is unique, show the child region there so the vanished after is visible
            if len(bhits) == 1:
                pos = bhits[0] - 1
                lo, hi = pos, min(len(rl), pos + k + 12)
                L.append(f"  -> child around the unique 'before' match (lines {pos + 1}..{hi}):")
                for j in range(lo, hi):
                    L.append(f"      child:{j + 1:>4} {rl[j]}")
    else:
        L.append("(no conflict block)")

    text = "\n".join(L) + "\n"
    if args.stdout:
        print(text)
    else:
        out_dir = config.OUTPUT_DIR / "diagnostics"
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"scenario_{proj}_{short}.txt"
        out.write_text(text, encoding="utf-8")
        print(f"wrote {out}")
        print("\n".join(L[:6]))


if __name__ == "__main__":
    main()
