"""One-off diagnostic: show a conflict block + the exact anchors resolution_region uses, and what
(if anything) sits between them in the child file. Replicates groundtruth.resolution_region's logic
so we can see WHY the developer region came out empty.

Writes the report to a file (terminal output can be too long to copy):

    python evaluation/trace_anchor_extraction.py                       # defaults to RxJava / JDime
    python evaluation/trace_anchor_extraction.py --project halo --tool JDime
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from conflictagent import config, data, merge, groundtruth, validate   # noqa: E402

ANCHOR_K = (3, 4, 5)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="RxJava")
    ap.add_argument("--tool", default="JDime")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    out_lines: list[str] = []

    def w(s: str = "") -> None:
        out_lines.append(s)

    lab = next((l for l in data.load_manual_labels()
                if l.project == args.project and l.tool == args.tool), None)
    if lab is None:
        print(f"no label for {args.project}/{args.tool}")
        return

    f = data.load_scenario_files(lab.project, lab.commit)
    merged, _ = merge.reconstruct_merged(f["base"], f["left"], f["right"])
    idx, ov = groundtruth.select_target_block(merged, lab.merged_snippet)
    w(f"{args.project}/{args.tool}  target_idx={idx} overlap={ov} "
      f"n_blocks={len(validate.conflict_blocks(merged))}")
    w()

    mlines = merged.splitlines()
    starts = [i for i, l in enumerate(mlines) if l.startswith("<<<<<<<")]
    ends = [i for i, l in enumerate(mlines) if l.startswith(">>>>>>>")]
    si, ei = starts[idx], ends[idx]
    w(f"merged: conflict block lines {si}..{ei}")
    w("=== merged conflict block + 5 lines of context each side ===")
    for i in range(max(0, si - 5), min(len(mlines), ei + 6)):
        mark = ">>" if si <= i <= ei else "  "
        w(f"{mark}{i:4d}| {mlines[i]}")

    rl = f["child"].splitlines()
    w(f"\n=== child file: {len(rl)} lines, first 25 ===")
    for i, l in enumerate(rl[:25]):
        w(f"{i:4d}| {l}")

    w("\n=== anchor trial per k (replicating resolution_region) ===")
    for k in ANCHOR_K:
        before = mlines[si - k:si]
        after = mlines[ei + 1:ei + 1 + k]
        w(f"\n--- k={k} ---")
        w(f"  before anchor ({k} lines above block): {before}")
        w(f"  after  anchor ({k} lines below block): {after}")
        if len(before) < k or len(after) < k:
            w("  -> not enough context for this k, skip")
            continue
        bi = [i for i in range(len(rl) - k + 1) if rl[i:i + k] == before]
        w(f"  before matches in child at: {bi}  ({'unique' if len(bi) == 1 else 'non-unique/none'})")
        if len(bi) != 1:
            continue
        start = bi[0] + k
        ai = [j for j in range(start, len(rl) - k + 1) if rl[j:j + k] == after]
        w(f"  after  matches in child at (from {start}): {ai}  ({'unique' if len(ai) == 1 else 'non-unique/none'})")
        if len(ai) != 1:
            continue
        region = rl[start:ai[0]]
        w(f"  => extracted region = child[{start}:{ai[0]}] = {region!r}  (status=ok)")
        w(f"  => before-anchor ends at {start}, after-anchor starts at {ai[0]}, "
          f"{ai[0] - start} line(s) between")

    out_path = Path(args.out) if args.out else (
        config.OUTPUT_DIR / "diag" / f"anchor_{args.project}_{args.tool}.txt")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(out_lines), encoding="utf-8")
    print(f"wrote {len(out_lines)} lines -> {out_path}")


if __name__ == "__main__":
    main()
