"""Calibrate the LLM-as-judge against ConflictBench's manual desirability labels.

Trust check before the judge is used for headline numbers: run judge.judge_equivalent on the
manual (tool resolution, developer, desirable 0/1) triples and measure agreement with the human
labels (accuracy / precision / recall, treating the human label as ground truth). High agreement
=> the automated judge is defensible.

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
from conflictagent import config, data, judge  # noqa: E402


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
    print(f"Calibrating judge ({config.JUDGE_MODEL[1]}) on {len(labels)} labels")
    with open(out_path, "w", encoding="utf-8") as fh:
        for i, lab in enumerate(labels):
            if not lab.tool_resolution.strip():      # tool produced no resolution to judge
                skipped += 1
                continue
            try:
                v = judge.judge_equivalent(lab.tool_resolution, lab.developer)
                eq = v["equivalent"]
            except Exception as e:
                eq, v = None, {"error": repr(e)}
            rec = {"project": lab.project, "tool": lab.tool, "manual": lab.desirable,
                   "judge": eq, "reason": v.get("reason", "")}
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            if eq is None:
                unparsed += 1
                continue
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
    print("\n=== judge vs human (human label = ground truth) ===")
    print(f"  judged: {n}   skipped(empty): {skipped}   unparsed: {unparsed}")
    print(f"  TP={tp}  FP={fp}  TN={tn}  FN={fn}")
    print(f"  accuracy={acc:.1%}  precision={prec:.1%}  recall={rec_:.1%}")
    print(f"\nRecords -> {out_path}")


if __name__ == "__main__":
    main()
