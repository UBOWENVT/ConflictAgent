"""Compare the LLM solvers vs the 5 ConflictBench merge tools on developer-match,
stratified by Valid Conflict, under TWO scoring instruments:

  * human-label    : tool desirability = ConflictBench's human label (lenient).
  * single-instrument : tool desirability = OUR Claude judge's verdict, i.e. the
                     SAME instrument that scored the LLM -> apples-to-apples.

Both use the OVERALL (coverage) convention: a tool that punted (left conflict
markers) OR had no applicable resolution counts as a MISS, because the LLM
almost always produces a resolution. This is the fair metric when one side
selectively abstains. The "among-resolved" rate is shown only as context (it is
confounded by punt rate -- a tool that punts the hard cases looks artificially
good on it).

It also prints the judge's developer-match calibration (judge verdict vs human
label, on the SAME tool resolutions) overall and split by conflict type -- a
characterization of the measuring instrument, not of any solver.

Inputs are auto-discovered (override with flags):
  --calib  newest outputs/judge_calibration/calib_*.jsonl
  --eval   newest outputs/eval/eval_<scheme>_complete.jsonl  (else eval_<scheme>_*.jsonl)

Run:  python scripts/compare_tools.py                 # scheme A, newest files
      python scripts/compare_tools.py --scheme B
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from conflictagent import config, data  # noqa: E402

TOOLS = data.TOOLS  # ["FSTMerge","JDime","IntelliMerge","AutoMerge","KDIFF3"]


def _newest(pattern: str) -> str | None:
    hits = sorted(glob.glob(pattern), key=lambda p: Path(p).stat().st_mtime, reverse=True)
    return hits[0] if hits else None


def _find_eval(scheme: str, override: str | None) -> str:
    if override:
        return override
    d = str(config.OUTPUT_DIR / "eval")
    return (_newest(f"{d}/eval_{scheme}_complete.jsonl")
            or _newest(f"{d}/eval_{scheme}_*.jsonl")
            or sys.exit(f"no eval file found for scheme {scheme} under {d}"))


def _find_calib(override: str | None) -> str:
    if override:
        return override
    d = str(config.OUTPUT_DIR / "judge_calibration")
    return _newest(f"{d}/calib_*.jsonl") or sys.exit(f"no calib file found under {d}")


def _rate(hit: int, n: int) -> str:
    return f"{hit:3d}/{n:<3d} = {100 * hit / n:5.1f}%" if n else "   n/a"


def _clf(judge: bool, manual: bool) -> str:
    return {(True, True): "tp", (True, False): "fp",
            (False, False): "tn", (False, True): "fn"}[(bool(judge), bool(manual))]


def _calib_stats(recs: list[dict]) -> str:
    c = {"tp": 0, "fp": 0, "tn": 0, "fn": 0}
    for r in recs:
        c[_clf(r["judge"], r["manual"])] += 1
    n = sum(c.values())
    if not n:
        return "n=0"
    acc = (c["tp"] + c["tn"]) / n
    prec = c["tp"] / (c["tp"] + c["fp"]) if (c["tp"] + c["fp"]) else 0.0
    rec = c["tp"] / (c["tp"] + c["fn"]) if (c["tp"] + c["fn"]) else 0.0
    return (f"n={n:3d}  acc={acc:5.1%}  prec={prec:5.1%}  rec={rec:5.1%}   "
            f"(TP{c['tp']} FP{c['fp']} TN{c['tn']} FN{c['fn']})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scheme", default="A", choices=["A", "B"])
    ap.add_argument("--calib", default=None)
    ap.add_argument("--eval", default=None)
    args = ap.parse_args()

    calib_path = _find_calib(args.calib)
    eval_path = _find_eval(args.scheme, args.eval)
    print(f"calib : {calib_path}")
    print(f"eval  : {eval_path}")

    # --- LLM developer-match per (provider, project); project is a unique scenario key ---
    llm: dict[str, dict[str, dict]] = {}
    n_err = 0
    for line in open(eval_path, encoding="utf-8"):
        r = json.loads(line)
        if r.get("kind") != "llm":
            continue
        if r.get("status") == "error":
            n_err += 1
            continue
        if r.get("status") == "resolved" and r.get("dev_status") == "ok" and r.get("dev_match") is not None:
            proj = r["id"].split("@")[0]
            llm.setdefault(r["provider"], {})[proj] = {"dm": bool(r["dev_match"]),
                                                        "vc": r.get("valid_conflict")}
    if n_err:
        print(f"  WARNING: eval file has {n_err} error records -- may be an unrecovered run")
    providers = sorted(llm)
    if not providers:
        sys.exit("no usable LLM dev-match records in eval file")

    # Comparable set = scenarios with a dev-match for EVERY provider (common, fair denom).
    common = set.intersection(*[set(llm[p]) for p in providers])
    vc_of = {pj: llm[providers[0]][pj]["vc"] for pj in common}
    true_set = sorted(pj for pj in common if vc_of[pj] is True)
    false_set = sorted(pj for pj in common if vc_of[pj] is False)
    print(f"\ncomparable scenarios (dev-match for all of {providers}): {len(common)}  "
          f"-> TRUE {len(true_set)} | FALSE {len(false_set)}\n")

    # --- tool HUMAN-label view (authoritative punt logic + 4 overrides, via data layer) ---
    human: dict[tuple[str, str], dict] = {}
    for lab in data.load_manual_labels():
        human[(lab.project, lab.tool)] = {"punt": lab.is_punt, "desirable": lab.desirable}

    # --- tool SINGLE-INSTRUMENT view (our judge's verdicts) from the calibration file ---
    si: dict[tuple[str, str], str] = {}          # (project,tool) -> 'punt'|'hit'|'miss'
    calib_des: list[dict] = []                    # desirability records, for instrument calibration
    for line in open(calib_path, encoding="utf-8"):
        r = json.loads(line)
        key = (r["project"], r["tool"])
        if r.get("kind") == "detection":
            si[key] = "punt"
        elif r.get("kind") == "desirability" and r.get("judge") is not None:
            si[key] = "hit" if r["judge"] else "miss"
            calib_des.append(r)

    # --- (Q3.2) the measuring instrument itself: judge vs human, overall + by conflict type ---
    print("### judge developer-match calibration (judge verdict vs human, on tool resolutions) ###")
    print("  ALL  ", _calib_stats(calib_des))
    print("  TRUE ", _calib_stats([r for r in calib_des if r.get("valid_conflict") is True]))
    print("  FALSE", _calib_stats([r for r in calib_des if r.get("valid_conflict") is False]))
    print("  (high precision = trust its YES; low recall = it under-credits -> rates are lower bounds)\n")

    def tool_overall(tool: str, subset: list[str], instrument: str) -> tuple[int, int, int, int]:
        """Return (hits, judged_or_resolved, punts, absent) under the OVERALL convention."""
        hit = judged = punt = absent = 0
        for pj in subset:
            if instrument == "human":
                h = human.get((pj, tool))
                if h is None:
                    absent += 1
                elif h["punt"]:
                    punt += 1
                else:
                    judged += 1
                    hit += 1 if h["desirable"] else 0
            else:  # single-instrument
                v = si.get((pj, tool))
                if v is None:
                    absent += 1
                elif v == "punt":
                    punt += 1
                else:
                    judged += 1
                    hit += 1 if v == "hit" else 0
        return hit, judged, punt, absent

    def report(name: str, subset: list[str]) -> None:
        n = len(subset)
        print(f"===== {name} (n={n}) =====")
        print(f"  {'solver / tool':<14}{'human-label':>16}{'single-instrument':>20}{'punt':>7}{'absent':>8}")
        rows = []
        for p in providers:                       # LLM: single instrument only (always our judge)
            hit = sum(1 for pj in subset if llm[p][pj]["dm"])
            rows.append((f"LLM {p}", None, hit / n if n else 0, _rate(hit, n), "", ""))
        for t in TOOLS:
            h_hit, _, _, _ = tool_overall(t, subset, "human")
            s_hit, _, s_punt, s_abs = tool_overall(t, subset, "single")
            rows.append((t, h_hit / n if n else 0, s_hit / n if n else 0,
                         _rate(s_hit, n), str(s_punt), str(s_abs)))
        rows.sort(key=lambda x: x[2], reverse=True)   # rank by single-instrument rate
        for label, hrate, _srate, scell, punt, absent in rows:
            hcell = "      --" if hrate is None else f"{100 * hrate:5.1f}%"
            print(f"  {label:<14}{hcell:>16}{scell:>20}{punt:>7}{absent:>8}")
        print()

    report("TRUE conflicts (overlapping edits)", true_set)
    report("FALSE conflicts (compatible / non-overlapping edits)", false_set)
    print("Note: OVERALL convention (punt / not-applicable = miss). 'single-instrument' scores BOTH\n"
          "LLM and tools with our Claude judge; 'human-label' uses ConflictBench's labels for tools.")


if __name__ == "__main__":
    main()
