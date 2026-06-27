"""Run the DeepEval suite on the solver outputs — Dataset B: ① + ② over the solver line.

Scores every solver resolution in the complete set with BOTH metrics:
  ① Resolution Acceptability (GEval, LLM judge) — does the solver's resolution match what the
     developer actually did? This is the headline: the developer-match acceptance rate.
  ② Structural Validity (deterministic, no LLM) — no leftover markers; parses (javalang); no
     over-scoped duplicate declarations.

The two are reported INDEPENDENTLY (② does NOT gate ①): ① is the semantic headline, ② is a
structural-soundness floor. Results are stratified by conflict type (true = headline) and provider.
This is the DeepEval re-measurement that supersedes the hand-built-judge 62-66% developer-match.

Cost: one Claude judge call (①) per case; ② is free. Use --limit for a cheap pipeline check first.

    python evaluation/run_solver_eval.py --limit 5    # ~5 judge calls, validate the pipeline
    python evaluation/run_solver_eval.py              # full run (~132 judge calls)

Manual per-case loop (not deepeval.evaluate()) for the same reason as run_suite.py: stratified
aggregation (by conflict type and provider) that evaluate()'s aggregate pass-rate does not give.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from conflictagent import config            # noqa: E402
from conflictagent.logging_setup import setup_logging  # noqa: E402
from evaluation import dataset, metrics     # noqa: E402

log = logging.getLogger(__name__)


def _rate(a: int, n: int) -> str:
    return f"{a}/{n} = {(a / n if n else 0.0):.1%}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="only the first N cases (cheap check)")
    ap.add_argument("--threshold", type=float, default=0.5, help="① GEval score -> accept cutoff")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    setup_logging(tag="solver_eval")

    cases = dataset.build_solver_testcases()
    if args.limit:
        cases = cases[:args.limit]
    acc_metric = metrics.resolution_acceptability_metric(threshold=args.threshold)
    val_metric = metrics.StructuralValidity()

    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_path = Path(args.out) if args.out else (
        config.OUTPUT_DIR / "deepeval" / f"solver_eval_{stamp}.jsonl")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # tallies[(provider, valid_conflict)] = {"n", "accept", "valid"}
    tallies: dict = defaultdict(lambda: {"n": 0, "accept": 0, "valid": 0})
    errors = 0
    log.info(f"Dataset B solver eval: {len(cases)} cases, judge={config.JUDGE_MODEL[1]}, "
             f"threshold={args.threshold}")
    with open(out_path, "w", encoding="utf-8") as fh:
        for i, tc in enumerate(cases, 1):
            m = tc.metadata
            sid, prov, vc = m["id"], m["provider"], m["valid_conflict"]

            # ① semantic judge (LLM call) — may fail on a transient API error; record and skip.
            try:
                a_score = acc_metric.measure(tc)
                accept = bool(acc_metric.success)
                a_reason = acc_metric.reason
            except Exception as e:
                errors += 1
                fh.write(json.dumps({"id": sid, "provider": prov, "valid_conflict": vc,
                                     "error": repr(e)}, ensure_ascii=False) + "\n")
                fh.flush()
                log.warning("  [%d/%d] %s/%s ① error: %s", i, len(cases), sid, prov, e)
                continue

            # ② structural validity (deterministic, no API) — never let it kill the run.
            try:
                val_metric.measure(tc)
                valid = bool(val_metric.success)
                v_reason = val_metric.reason
            except Exception as e:
                valid = False
                v_reason = f"② error: {e}"

            rec = {"id": sid, "provider": prov, "valid_conflict": vc,
                   "accept": accept, "accept_score": round(float(a_score), 3),
                   "structurally_valid": valid,
                   "accept_reason": a_reason, "valid_reason": v_reason}
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()

            t = tallies[(prov, vc)]
            t["n"] += 1
            t["accept"] += int(accept)
            t["valid"] += int(valid)

            if i % 10 == 0:
                log.info(f"  {i}/{len(cases)} done")

    _report(tallies, errors, out_path)


def _report(tallies: dict, errors: int, out_path: Path) -> None:
    """Stratified table: ① acceptance + ② validity by provider × conflict type, plus the headline."""
    providers = sorted({p for (p, _) in tallies})
    log.info(f"\n=== Dataset B: ① acceptance + ② structural validity "
             f"(by provider x conflict-type, errors={errors}) ===")
    log.info(f"  {'group':14}{'n':>4}   {'accept (①)':>15}   {'valid (②)':>15}")
    for prov in providers:
        for vc, label in ((True, "true"), (False, "false")):
            t = tallies.get((prov, vc))
            if not t:
                continue
            log.info(f"  {prov + ' ' + label:14}{t['n']:>4}   "
                     f"{_rate(t['accept'], t['n']):>15}   {_rate(t['valid'], t['n']):>15}")

    # headline: true conflicts, both providers pooled (the resume number)
    ht = {"n": 0, "accept": 0, "valid": 0}
    for (p, vc), t in tallies.items():
        if vc is True:
            ht["n"] += t["n"]
            ht["accept"] += t["accept"]
            ht["valid"] += t["valid"]
    log.info("  " + "-" * 54)
    log.info(f"  {'HEADLINE true':14}{ht['n']:>4}   "
             f"{_rate(ht['accept'], ht['n']):>15}   {_rate(ht['valid'], ht['n']):>15}   "
             f"<- supersedes hand-judge 62-66%")
    log.info(f"\n  per-case records -> {out_path}")


if __name__ == "__main__":
    main()
