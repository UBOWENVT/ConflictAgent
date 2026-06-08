"""Calibrate the LLM judge against ConflictBench's manual desirability labels.

For each labeled (scenario, tool) pair, build a (tool_resolution, developer_resolution) pair to
judge, PREFERRING the real resolved files and falling back to cleaned xlsx snippets:

  1. select the annotated conflict block via the xlsx MERGED snippet (not blindly block #0)
  2. if both the tool's file and the child file extract that block cleanly (anchors unique) ->
     use those file regions (same git-block span; consistent)
  3. otherwise -> fall back to cleaned xlsx snippets for BOTH sides (same human span; consistent)

Then judge equivalence and compare to the human label (accuracy / precision / recall). The per-pair
`source` (file vs xlsx-fallback) is recorded so we can see how often each path is taken.

Run:  python scripts/calibrate_judge.py --limit 100   # cheap first pass
      python scripts/calibrate_judge.py                # all ~627 labels
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from conflictagent import config, data, groundtruth, judge, merge  # noqa: E402


def build_pair(lab: data.ManualLabel) -> tuple[str, str, str]:
    """Return (candidate, developer, source). source in {'file','xlsx'}.

    Prefer real-file region extraction; fall back to cleaned xlsx snippets when the files are
    missing or the anchors aren't unique. Both sides always come from the SAME source, so the
    pair is span-consistent.
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
                return tool_region, dev_region, "file"
    # fallback: cleaned xlsx snippets (both sides at the human annotation span)
    return (data.clean_xlsx_snippet(lab.tool_resolution),
            data.clean_xlsx_snippet(lab.developer), "xlsx")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="only the first N labels")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    labels = data.load_manual_labels()
    if args.limit:
        labels = labels[: args.limit]

    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_path = Path(args.out) if args.out else config.OUTPUT_DIR / "judge_calibration" / f"calib_{stamp}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    tp = fp = tn = fn = skipped = unparsed = 0
    src = {"file": 0, "xlsx": 0}
    det_total = det_true = 0  # tool punts: output still has conflict markers = a detection event
    print(f"Calibrating judge ({config.JUDGE_MODEL[1]}) on {len(labels)} labels")
    with open(out_path, "w", encoding="utf-8") as fh:
        for lab in labels:
            # A tool that LEFT the conflict unresolved (Strategy == 'still conflict') is a detection
            # event, not a resolution. It belongs to the detection metric, not desirability, so
            # exclude it here and tally it separately. Signal = authoritative human Strategy label.
            if lab.is_punt:
                det_total += 1
                if lab.valid_conflict:
                    det_true += 1
                fh.write(json.dumps({"project": lab.project, "tool": lab.tool, "kind": "detection",
                                     "valid_conflict": lab.valid_conflict, "manual": lab.desirable},
                                    ensure_ascii=False) + "\n")
                fh.flush()
                continue
            cand, dev, source = build_pair(lab)
            if source == "xlsx" and (not cand.strip() or not dev.strip()):
                skipped += 1  # genuinely-missing xlsx fallback (file path may have empty=deletion)
                continue
            try:
                v = judge.judge_equivalent(cand, dev)
                eq = v["equivalent"]
            except Exception as e:
                eq, v = None, {"error": repr(e)}
            rec = {"project": lab.project, "tool": lab.tool, "kind": "desirability", "source": source,
                   "manual": lab.desirable, "judge": eq, "reason": v.get("reason", "")}
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            if eq is None:
                unparsed += 1
                continue
            src[source] += 1
            if eq and lab.desirable:
                tp += 1
            elif eq and not lab.desirable:
                fp += 1
            elif not eq and not lab.desirable:
                tn += 1
            else:
                fn += 1

    n = tp + fp + tn + fn
    acc = (tp + tn) / n if n else 0.0
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec_ = tp / (tp + fn) if (tp + fn) else 0.0
    print("\n=== DESIRABILITY judge vs human (clean tool resolutions only) ===")
    print(f"  judged: {n}   skipped(empty): {skipped}   unparsed: {unparsed}")
    print(f"  source: file={src['file']}  xlsx-fallback={src['xlsx']}")
    print(f"  TP={tp}  FP={fp}  TN={tn}  FN={fn}")
    print(f"  accuracy={acc:.1%}  precision={prec:.1%}  recall={rec_:.1%}")
    print("\n=== DETECTION events (tool left conflict markers; excluded from desirability above) ===")
    if det_total:
        print(f"  tool punts: {det_total}   on true conflicts: {det_true}   "
              f"detection precision: {det_true / det_total:.1%}")
    else:
        print("  none in this slice")
    print(f"\nRecords -> {out_path}")


if __name__ == "__main__":
    main()
