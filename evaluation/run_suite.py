"""Run the DeepEval suite — Phase 1: ③ judge meta-validation.

Runs the ① Resolution Acceptability (GEval) judge over the 303 human-labeled desirability cases
and compares its accept/reject verdicts to the human labels: a confusion matrix (accuracy /
precision / recall) plus a dump of disagreements with the judge's own reason (failure-mode
analysis). This is the DeepEval-native re-measurement of judge credibility.

The numbers are whatever GEval produces. This is a MORE-informed judge than the original (it also
sees the conflict block), so the figures are not expected to match the hand-built calibration —
and per the project decision that is fine; new real numbers are the point.

Cost: one Claude judge call per case. Use --limit for a cheap pipeline check first.

    python evaluation/run_suite.py --limit 20      # ~20 calls, validate the pipeline
    python evaluation/run_suite.py                 # full 303 calls

Design note: this uses a manual per-case loop rather than deepeval.evaluate() because ③ needs a
custom join of judge verdict vs human label (a confusion matrix + disagreement dump), which the
aggregate pass-rate reporting of evaluate() does not provide. The later solver-evaluation runner
(Dataset B, ① + ② together) is the place for evaluate().
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from conflictagent import config            # noqa: E402
from conflictagent.logging_setup import setup_logging  # noqa: E402
from evaluation import dataset, metrics     # noqa: E402

log = logging.getLogger(__name__)


def _meta(tc) -> dict:
    m = tc.metadata or {}
    return {"project": m.get("project"), "commit": m.get("commit"),
            "tool": m.get("tool"), "source": m.get("source")}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="only the first N cases (cheap check)")
    ap.add_argument("--threshold", type=float, default=0.5, help="GEval score -> accept cutoff")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    setup_logging(tag="metaval")

    cases = dataset.build_metavalidation_testcases(limit=args.limit)
    metric = metrics.resolution_acceptability_metric(threshold=args.threshold)

    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_path = Path(args.out) if args.out else (
        config.OUTPUT_DIR / "deepeval" / f"metaval_{stamp}.jsonl")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    tp = fp = tn = fn = errors = 0
    disagreements: list[dict] = []
    log.info(f"3 judge meta-validation: {len(cases)} cases, judge={config.JUDGE_MODEL[1]}, "
             f"threshold={args.threshold}")
    with open(out_path, "w", encoding="utf-8") as fh:
        for i, tc in enumerate(cases, 1):
            human = bool(tc.metadata["human_desirable"])
            try:
                score = metric.measure(tc)
                verdict = bool(metric.success)         # score >= threshold
                reason = metric.reason
            except Exception as e:
                errors += 1
                fh.write(json.dumps({**_meta(tc), "human": human, "error": repr(e)},
                                    ensure_ascii=False) + "\n")
                fh.flush()
                continue

            rec = {**_meta(tc), "human": human, "judge": verdict,
                   "score": round(float(score), 3), "reason": reason}
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()

            if verdict and human:
                tp += 1
            elif verdict and not human:
                fp += 1
            elif not verdict and not human:
                tn += 1
            else:
                fn += 1
            if verdict != human:
                disagreements.append(rec)

            if i % 20 == 0:
                log.info(f"  {i}/{len(cases)} done")

    n = tp + fp + tn + fn
    acc = (tp + tn) / n if n else 0.0
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    log.info(f"\n=== 1 GEval judge vs human ({n} cases, errors={errors}) ===")
    log.info(f"  TP={tp}  FP={fp}  TN={tn}  FN={fn}")
    log.info(f"  accuracy={acc:.1%}  precision={prec:.1%}  recall={rec:.1%}")
    log.info(f"\n  disagreements: {len(disagreements)}  (full records -> {out_path})")
    for d in disagreements[:10]:
        kind = "FP judge-says-ok " if d["judge"] else "FN judge-says-no "
        log.info(f"   [{kind}] {d['project']}/{d['tool']}  score={d['score']}  {(d['reason'] or '')[:90]}")


if __name__ == "__main__":
    main()
