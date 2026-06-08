"""Evaluate LLM merge-conflict resolution on ConflictBench — Detection + Desirability per model.

For each reconstructable Java scenario x provider:
  agent.resolve -> a PUNT (the model declares a true conflict) OR a resolution of the annotated
  target block.

  DETECTION (no judge): predicted_true = punt; compared to the human 'Valid Conflict' label.
     precision = punts that are true conflicts / all punts
     recall    = punts that are true conflicts / all true conflicts
  This is directly comparable to the 5 merge tools' detection (their punt = 'still conflict').

  DESIRABILITY (calibrated judge v2, only on PRODUCED resolutions): judge the LLM resolution vs the
  developer's resolution of the SAME target block, extracted from the child FILE so the two are
  span-consistent. Scored only when the developer region extracts cleanly ('ok').

Everything stratified by Valid Conflict (true / false). Incremental JSONL + per-model summary.

Run:  python scripts/run_eval.py --providers openai gemini            # all Java scenarios
      python scripts/run_eval.py --providers openai --limit 10        # quick smoke
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from conflictagent import config, data, agent, groundtruth, judge, merge  # noqa: E402


def _new_stats() -> dict:
    return {
        "det": {"n": 0, "punt": 0, "punt_true": 0, "true_total": 0},
        "des": {"judged": 0, "acceptable": 0,
                "by_vc": {True: {"j": 0, "a": 0}, False: {"j": 0, "a": 0}}},
        "errors": 0,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--providers", nargs="+", default=["openai", "gemini"])
    ap.add_argument("--limit", type=int, default=0, help="0 = all reconstructable Java scenarios")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    usable = []
    for s in data.load_scenarios(java_only=True):
        fv = data.load_full_versions(s)
        if fv:
            usable.append((s, fv))
    if args.limit:
        usable = usable[: args.limit]

    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_path = Path(args.out) if args.out else config.OUTPUT_DIR / "eval" / f"eval_{stamp}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    stats = {p: _new_stats() for p in args.providers}
    print(f"Evaluating {len(usable)} Java scenarios x {args.providers} "
          f"(judge={config.JUDGE_MODEL[1]})")

    with open(out_path, "w", encoding="utf-8") as fh:
        for s, fv in usable:
            # Developer's resolution of the target block (span-consistent ground truth), once.
            merged, _ = merge.reconstruct_merged(fv["base"], fv["left"], fv["right"])
            tgt, _ = groundtruth.select_target_block(merged, s.conflict_chunk)
            dev_region, dev_status = (None, "no_block")
            if tgt >= 0 and "child" in fv:
                dev_region, dev_status = groundtruth.resolution_region(fv["child"], merged, tgt)

            for p in args.providers:
                st = stats[p]
                try:
                    rec = agent.resolve(p, s, fv)
                except Exception as e:
                    st["errors"] += 1
                    fh.write(json.dumps({"id": s.id, "provider": p, "error": repr(e)}) + "\n")
                    fh.flush()
                    continue

                # --- Detection ---
                st["det"]["n"] += 1
                if s.valid_conflict:
                    st["det"]["true_total"] += 1
                punt = bool(rec.get("predicted_true_conflict", False))
                if punt:
                    st["det"]["punt"] += 1
                    if s.valid_conflict:
                        st["det"]["punt_true"] += 1

                # --- Desirability (only for produced resolutions + clean developer region) ---
                desirable = None
                if rec["status"] == "resolved" and dev_status == "ok" and dev_region is not None:
                    try:
                        acc = judge.judge_equivalent(rec["final_resolution"], dev_region)["equivalent"]
                    except Exception:
                        acc = None
                    if acc is not None:
                        st["des"]["judged"] += 1
                        st["des"]["acceptable"] += int(acc)
                        b = st["des"]["by_vc"][bool(s.valid_conflict)]
                        b["j"] += 1
                        b["a"] += int(acc)
                        desirable = acc

                fh.write(json.dumps({
                    "id": s.id, "provider": p, "valid_conflict": s.valid_conflict,
                    "status": rec["status"], "punt": punt, "n_blocks": rec.get("n_blocks"),
                    "dev_status": dev_status, "desirable": desirable,
                    "final_valid": rec.get("final_valid"),
                }, ensure_ascii=False) + "\n")
                fh.flush()

    # --- summary ---
    for p in args.providers:
        d, de = stats[p]["det"], stats[p]["des"]
        prec = d["punt_true"] / d["punt"] if d["punt"] else 0.0
        rec_ = d["punt_true"] / d["true_total"] if d["true_total"] else 0.0
        des_rate = de["acceptable"] / de["judged"] if de["judged"] else 0.0
        print(f"\n=== {p} ===")
        print(f"  scenarios: {d['n']}   errors: {stats[p]['errors']}")
        print(f"  DETECTION: punts={d['punt']} (true={d['punt_true']}) of {d['true_total']} true conflicts")
        print(f"    precision={prec:.1%}  recall={rec_:.1%}")
        print(f"  DESIRABILITY (produced resolutions, judged vs developer): judged={de['judged']}")
        print(f"    acceptable rate={des_rate:.1%}")
        for vc, lab in [(False, "false/resolvable"), (True, "true conflict")]:
            b = de["by_vc"][vc]
            r = b["a"] / b["j"] if b["j"] else 0.0
            print(f"      {lab}: {b['a']}/{b['j']} = {r:.1%}")
    print(f"\nRecords -> {out_path}")


if __name__ == "__main__":
    main()
