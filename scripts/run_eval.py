"""Evaluate LLM merge-conflict resolution on ConflictBench (2026-06-08 redirect).

SUPERSEDED NOTE (2026-06-27): the solver developer-match numbers this script's full-mode summary
prints come from the hand-built judge v2 and are SUPERSEDED by the DeepEval suite -- see
docs/RESULTS.md 'DeepEval Solver Results' for the current figures. This script's current primary
use is Dataset B data production via --no-judge (runs the solver, saves final_resolution; the
DeepEval suite re-judges separately).

Result meaning comes from three things, not prompt cleverness:
  1. a judge calibrated to the human labels (judge v2, scripts/calibrate_judge.py);
  2. trivial BASELINES (pick-left / pick-right / pick-longer / union) so the LLM's selling point is
     how far it beats the strongest baseline (developers pick a single side ~57% of the time, so the
     baseline is strong and must be shown);
  3. comparability with the 5 merge tools (same desirability notion, same target block).

Per reconstructable Java scenario x provider, under --scheme A or B:
  agent.resolve -> a resolution of the annotated target block (scheme B may instead PUNT).

  DETECTION (scheme B only): predicted_true = punt, vs the human 'Valid Conflict' label
     (precision/recall) — comparable to the tools' 'still conflict'.
  CONFIDENCE CALIBRATION (both schemes): desirability rate bucketed by the model's self-reported
     confidence — does low confidence track low desirability?
  DESIRABILITY, two notions, both judged by the calibrated judge on the SAME target block:
     - developer-match: candidate vs the developer's resolution (child file, span-consistent);
     - standalone-valid: candidate vs the conflict itself (base/left/right), no reference answer.
       MEANINGFUL ONLY for false conflicts (an objective merge exists; calibrated acc 85% /
       precision 88% on 40 hand labels). Ill-posed for true conflicts (no context-free correct
       answer) -> developer-match is the primary metric there.
     The gap between them = "resolved correctly but differently from the developer".

Trivial baselines are judged once per scenario (provider-independent). Everything stratified by
Valid Conflict. Incremental JSONL + per-model summary.

Run:  python scripts/run_eval.py --scheme A --providers openai gemini      # all Java scenarios
      python scripts/run_eval.py --scheme A --providers openai --limit 10  # quick smoke
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from conflictagent import config, data, agent, groundtruth, judge, merge, validate  # noqa: E402
from conflictagent.logging_setup import setup_logging  # noqa: E402

log = logging.getLogger(__name__)

BASELINES = ("pick-left", "pick-right", "pick-longer", "union")
CONF_BUCKETS = ("high", "medium", "low", "")   # "" = model gave no/unparsed confidence


def _nonblank(text: str) -> int:
    return sum(1 for l in (text or "").splitlines() if l.strip())


def _build_baselines(left: str, base: str, right: str) -> dict[str, str]:
    longer = left if _nonblank(left) >= _nonblank(right) else right
    union = (left + "\n" + right) if (left and right) else (left or right)
    return {"pick-left": left, "pick-right": right, "pick-longer": longer, "union": union}


def _judge_pair(kind: str, candidate: str, dev_region: str | None,
                left: str, base: str, right: str) -> bool | None:
    """kind='dev' -> developer-match (needs dev_region); kind='std' -> standalone-valid."""
    try:
        if kind == "dev":
            if dev_region is None:
                return None
            return judge.judge_equivalent(candidate, dev_region)["equivalent"]
        return judge.judge_standalone(candidate, left, base, right)["equivalent"]
    except Exception:
        return None


def _prov_stats() -> dict:
    by_vc = lambda: {True: {"j": 0, "a": 0}, False: {"j": 0, "a": 0}}  # noqa: E731
    by_conf = lambda: {c: {"j": 0, "a": 0} for c in CONF_BUCKETS}      # noqa: E731
    return {
        "det": {"punt": 0, "punt_true": 0, "true_total": 0},
        "dev": {"j": 0, "a": 0, "by_vc": by_vc(), "by_conf": by_conf()},
        "std": {"j": 0, "a": 0, "by_vc": by_vc(), "by_conf": by_conf()},
        "resolved": 0, "punt": 0, "errors": 0,
    }


def _base_stats() -> dict:
    by_vc = lambda: {True: {"j": 0, "a": 0}, False: {"j": 0, "a": 0}}  # noqa: E731
    return {n: {"dev": {"j": 0, "a": 0, "by_vc": by_vc()},
                "std": {"j": 0, "a": 0, "by_vc": by_vc()}} for n in BASELINES}


def _acc(rec_kind: dict, vc: bool | None, acc: bool | None, conf: str | None = None) -> None:
    """Accumulate one judged outcome into a {'j','a','by_vc'[,'by_conf']} bucket set."""
    if acc is None:
        return
    rec_kind["j"] += 1
    rec_kind["a"] += int(acc)
    if vc is not None:
        b = rec_kind["by_vc"][bool(vc)]
        b["j"] += 1
        b["a"] += int(acc)
    if conf is not None and "by_conf" in rec_kind:
        c = rec_kind["by_conf"].get(conf if conf in CONF_BUCKETS else "")
        c["j"] += 1
        c["a"] += int(acc)


def _rate(b: dict) -> str:
    return f"{b['a']}/{b['j']} = {(b['a']/b['j'] if b['j'] else 0.0):.1%}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scheme", choices=config.SCHEMES, default=config.DEFAULT_SCHEME)
    ap.add_argument("--providers", nargs="+", default=["openai", "gemini"])
    ap.add_argument("--limit", type=int, default=0, help="0 = all reconstructable Java scenarios")
    ap.add_argument("--no-baselines", action="store_true", help="skip trivial baselines (saves judge calls)")
    ap.add_argument("--no-judge", action="store_true",
                    help="skip ALL Claude judge calls (baselines + dev/std); only run the solver and "
                         "save final_resolution. dev_match/standalone come out null. Use this for "
                         "Dataset B data production -- the DeepEval suite re-judges separately.")
    ap.add_argument("--only-ids", nargs="+", default=None,
                    help="run only these scenario ids (e.g. to recover specific failed scenarios)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    setup_logging(tag=f"eval_{args.scheme}")

    usable = []
    for s in data.load_scenarios(java_only=True):
        fv = data.load_full_versions(s)
        if fv:
            usable.append((s, fv))
    if args.limit:
        usable = usable[: args.limit]
    if args.only_ids:
        want = set(args.only_ids)
        usable = [(s, fv) for (s, fv) in usable if s.id in want]
        found = {s.id for (s, fv) in usable}
        missing = want - found
        if missing:
            print(f"WARNING: --only-ids not found among reconstructable scenarios: {sorted(missing)}")

    stamp = time.strftime("%Y%m%d_%H%M%S")
    prov_tag = "both" if set(args.providers) == {"openai", "gemini"} else "-".join(args.providers)
    mode_tag = "nojudge" if args.no_judge else "full"
    out_path = (Path(args.out) if args.out else
                config.OUTPUT_DIR / "eval" / "runs"
                / f"eval_{args.scheme}_{prov_tag}_{mode_tag}_{stamp}.jsonl")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    pstats = {p: _prov_stats() for p in args.providers}
    bstats = _base_stats()
    timing = {"solve": 0.0, "judge": 0.0, "base_judge": 0.0,
              "rounds": {p: {} for p in args.providers}}  # rounds[p][n_rounds] = scenario count
    log.info(f"Evaluating {len(usable)} Java scenarios x {args.providers} | scheme={args.scheme} "
             f"| judge={'OFF (no-judge)' if args.no_judge else config.JUDGE_MODEL[1]} "
             f"| baselines={'off' if (args.no_baselines or args.no_judge) else 'on'}")

    timing_path = out_path.with_suffix(".timing.csv")
    with open(out_path, "w", encoding="utf-8") as fh, \
            open(timing_path, "w", encoding="utf-8") as tf:
        tf.write("idx,id,provider,status,n_rounds,final_valid,solve_secs,judge_secs\n")

        def emit(obj: dict) -> None:
            fh.write(json.dumps(obj, ensure_ascii=False) + "\n")
            fh.flush()

        def log_timing(idx, sid, provider, status, n_rounds, final_valid,
                       solve_s, judge_s) -> None:
            tf.write(f"{idx},{sid},{provider},{status},{n_rounds},{final_valid},"
                     f"{solve_s:.2f},{judge_s:.2f}\n")
            tf.flush()

        n_total = len(usable)
        for idx, (s, fv) in enumerate(usable, 1):
            log.info(f"  [{idx}/{n_total}] {s.id}")
            merged, _ = merge.reconstruct_merged(fv["base"], fv["left"], fv["right"])
            blocks = validate.conflict_blocks(merged)
            tgt, _ = groundtruth.select_target_block(merged, s.conflict_chunk)

            dev_region, dev_status = (None, "no_block")
            left = base = right = ""
            if tgt >= 0 and tgt < len(blocks):
                left, base, right = validate.split_diff3_block(blocks[tgt])
                if "child" in fv:
                    dev_region, dev_status = groundtruth.resolution_region(fv["child"], merged, tgt)

            # --- Trivial baselines (provider-independent; judged once) ---
            if not args.no_baselines and not args.no_judge and tgt >= 0:
                _bt = time.perf_counter()
                for name, cand in _build_baselines(left, base, right).items():
                    dm = _judge_pair("dev", cand, dev_region if dev_status == "ok" else None,
                                     left, base, right)
                    sv = _judge_pair("std", cand, None, left, base, right)
                    _acc(bstats[name]["dev"], s.valid_conflict, dm)
                    _acc(bstats[name]["std"], s.valid_conflict, sv)
                    emit({"kind": "baseline", "id": s.id, "baseline": name,
                          "valid_conflict": s.valid_conflict, "dev_status": dev_status,
                          "dev_match": dm, "standalone": sv})
                _bsecs = time.perf_counter() - _bt
                timing["base_judge"] += _bsecs
                log_timing(idx, s.id, "(baselines)", "judged", 0, "", 0.0, _bsecs)

            # --- LLM, per provider ---
            for p in args.providers:
                st = pstats[p]
                _t0 = time.perf_counter()
                try:
                    rec = agent.resolve(p, s, fv, scheme=args.scheme)
                except Exception as e:
                    st["errors"] += 1
                    _se = time.perf_counter() - _t0
                    timing["solve"] += _se
                    log_timing(idx, s.id, p, "error", 0, "", _se, 0.0)
                    emit({"kind": "llm", "id": s.id, "provider": p, "scheme": args.scheme,
                          "error": repr(e)})
                    continue
                solve_s = time.perf_counter() - _t0
                timing["solve"] += solve_s
                nr = rec.get("n_rounds", 0)
                timing["rounds"][p][nr] = timing["rounds"][p].get(nr, 0) + 1

                punt = bool(rec.get("predicted_true_conflict", False))
                if args.scheme == "B":
                    if s.valid_conflict:
                        st["det"]["true_total"] += 1
                    if punt:
                        st["det"]["punt"] += 1
                        if s.valid_conflict:
                            st["det"]["punt_true"] += 1

                dm = sv = None
                conf = rec.get("confidence", "")
                _j0 = time.perf_counter()
                if rec["status"] == "resolved":
                    st["resolved"] += 1
                    cand = rec["final_resolution"]
                    if not args.no_judge:
                        dm = _judge_pair("dev", cand, dev_region if dev_status == "ok" else None,
                                         left, base, right)
                        sv = _judge_pair("std", cand, None, left, base, right)
                        _acc(st["dev"], s.valid_conflict, dm, conf)
                        _acc(st["std"], s.valid_conflict, sv, conf)
                elif punt:
                    st["punt"] += 1
                judge_s = time.perf_counter() - _j0
                timing["judge"] += judge_s
                log_timing(idx, s.id, p, rec["status"], nr, rec.get("final_valid"),
                           solve_s, judge_s)

                emit({"kind": "llm", "id": s.id, "provider": p, "scheme": args.scheme,
                      "valid_conflict": s.valid_conflict, "status": rec["status"], "punt": punt,
                      "n_blocks": rec.get("n_blocks"), "n_rounds": nr, "confidence": conf,
                      "strategy": rec.get("strategy", ""), "dev_status": dev_status,
                      "dev_match": dm, "standalone": sv, "final_valid": rec.get("final_valid"),
                      # solver output text (actual_output for Dataset B) + the developer region it
                      # was judged against (expected_output); together they make dev_match auditable
                      # and let Dataset B reuse this run without re-calling the solver.
                      "final_resolution": rec.get("final_resolution", ""),
                      "dev_region": dev_region})

    _summary(args, pstats, bstats, out_path, timing)


def _summary(args, pstats: dict, bstats: dict, out_path: Path, timing: dict | None = None) -> None:
    for p in args.providers:
        st = pstats[p]
        log.info(f"\n=== {p}  (scheme {args.scheme}) ===")
        log.info(f"  resolved: {st['resolved']}   punts: {st['punt']}   errors: {st['errors']}")
        if args.scheme == "B":
            d = st["det"]
            prec = d["punt_true"] / d["punt"] if d["punt"] else 0.0
            recl = d["punt_true"] / d["true_total"] if d["true_total"] else 0.0
            log.info(f"  DETECTION: punts={d['punt']} (true={d['punt_true']}) of {d['true_total']} "
                     f"true conflicts -> precision={prec:.1%} recall={recl:.1%}")
        # developer-match (hand-built judge v2). NOTE: these solver numbers are SUPERSEDED by the
        # DeepEval suite -- see docs/RESULTS.md 'DeepEval Solver Results'. Kept as a full-mode
        # runtime diagnostic only; this script's current primary purpose is Dataset B data
        # production via --no-judge (judge OFF, so these lines read 0/0 there).
        dev = st["dev"]
        log.info(f"  DESIRABILITY developer-match  [hand-built judge v2 -- SUPERSEDED; "
                 f"current numbers in docs/RESULTS.md 'DeepEval Solver Results']: {_rate(dev)}")
        log.info(f"      true conflict : {_rate(dev['by_vc'][True])}")
        log.info(f"      false conflict: {_rate(dev['by_vc'][False])}")
        # standalone-valid is a correctness measure ONLY on false conflicts (an objective merge
        # exists); calibrated there at acc 85% / prec 88% (40 hand labels). On true conflicts it is
        # ill-posed (no context-free correct answer) -> reference only, NOT a correctness measure.
        std = st["std"]
        log.info(f"  DESIRABILITY standalone-valid [false conflicts only; calib acc 85%/prec 88%]: "
                 f"{_rate(std['by_vc'][False])}")
        log.info(f"      true conflict (ill-posed, reference only — use developer-match): "
                 f"{_rate(std['by_vc'][True])}")
        log.info("  CONFIDENCE CALIBRATION (developer-match rate by self-reported confidence):")
        for c in ("high", "medium", "low", ""):
            b = st["dev"]["by_conf"][c]
            if b["j"]:
                log.info(f"      {c or '(none)':<7}: {_rate(b)}")

    if not args.no_baselines:
        log.info("\n=== TRIVIAL BASELINES (provider-independent; the bar the LLM must clear) ===")
        for name in BASELINES:
            bs = bstats[name]
            log.info(f"  {name:<11} dev-match {_rate(bs['dev'])} | standalone {_rate(bs['std'])}")
        best = max(BASELINES, key=lambda n: (bstats[n]['dev']['a'] / bstats[n]['dev']['j'])
                   if bstats[n]['dev']['j'] else 0.0)
        bd = bstats[best]['dev']
        log.info(f"  strongest baseline (dev-match): {best} = "
                 f"{(bd['a']/bd['j'] if bd['j'] else 0.0):.1%}")

    if timing:
        log.info("\n=== TIMING / RETRIES (diagnostic) ===")
        log.info(f"  total solver={timing['solve']:.0f}s  judge(llm)={timing['judge']:.0f}s  "
                 f"judge(baselines)={timing['base_judge']:.0f}s")
        for p in args.providers:
            dist = timing["rounds"].get(p, {})
            n = sum(dist.values()) or 1
            avg = sum(k * v for k, v in dist.items()) / n
            order = "  ".join(f"{k}x{dist[k]}" for k in sorted(dist))
            log.info(f"  {p}: avg solver attempts={avg:.2f}  [attempts x scenarios: {order}]")
        log.info(f"  per-scenario CSV -> {out_path.with_suffix('.timing.csv')}")

    log.info(f"\nRecords -> {out_path}")


if __name__ == "__main__":
    main()
