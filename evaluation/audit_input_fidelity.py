"""Input-fidelity health check for the judge meta-validation set.

Measures three independent pollution classes in the inputs fed to the GEval judge, then crosses
them with the confusion matrix to report how much of the 98.4%/67% rests on trustworthy inputs.

  Defect 1 (file source): anchor extraction returns empty region (developer/tool repacked/renamed
            the block, e.g. import reorder) or anchor_not_unique -> degraded/fallback input.
  Defect 2 (xlsx source): hand-entered snippets with ellipsis / deleted lines -> partial code.
  Defect 3 (hidden chars): CR / tab / NBSP / zero-width / BOM from copy-paste into the xlsx.

No LLM calls. Writes a report file; joins the latest metaval_*.jsonl for the confusion-matrix cross.

    python evaluation/audit_input_fidelity.py
    python evaluation/audit_input_fidelity.py --metaval outputs/deepeval/metaval_20260625_180159.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from conflictagent import config, data, merge, groundtruth   # noqa: E402

# ellipsis variants Bowen used to elide rows: U+2026, runs of >=3 ASCII dots, spaced ". . ."
_ELLIPSIS = re.compile("\u2026|\\.\\s*\\.\\s*\\.")
_HIDDEN = {"\r": "CR", "\t": "TAB", "\xa0": "NBSP", "\u200b": "ZWSP",
           "\ufeff": "BOM", "\u3000": "IDEO_SPACE"}


def _has_ellipsis(s: str) -> bool:
    return bool(_ELLIPSIS.search(s or ""))


def _hidden_flags(s: str) -> set[str]:
    s = s or ""
    return {name for ch, name in _HIDDEN.items() if ch in s}


def _norm(t: str) -> str:
    """CRLF->LF + strip trailing whitespace per line (safe normalization for the rescue test)."""
    t = (t or "").replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in t.split("\n"))


def _empty(s) -> bool:
    return not (s or "").strip()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--metaval", default=None, help="metaval jsonl to cross with (default: newest)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    # locate metaval jsonl (judge verdicts) for the confusion-matrix cross
    mv_path = Path(args.metaval) if args.metaval else None
    if mv_path is None:
        cand = sorted((config.OUTPUT_DIR / "deepeval").glob("metaval_*.jsonl"))
        mv_path = cand[-1] if cand else None
    verdicts: dict[tuple, dict] = {}
    if mv_path and mv_path.exists():
        for line in mv_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            verdicts[(r.get("project"), r.get("commit"), r.get("tool"))] = r

    labels = [l for l in data.load_manual_labels() if not l.is_punt]

    merged_cache: dict[tuple, str | None] = {}

    def get_merged(proj: str, commit: str):
        key = (proj, commit)
        if key not in merged_cache:
            f = data.load_scenario_files(proj, commit)
            if {"base", "left", "right"} <= f.keys():
                m, _ = merge.reconstruct_merged(f["base"], f["left"], f["right"])
                merged_cache[key] = m
            else:
                merged_cache[key] = None
        return merged_cache[key], data.load_scenario_files(proj, commit)

    recs: list[dict] = []
    src_counter = Counter()
    file_status = Counter()
    overlap_buckets = Counter()
    rescue = {"anchor_fail": 0, "rescued": 0, "still_fail": 0}

    for lab in labels:
        rec = {"project": lab.project, "commit": lab.commit, "tool": lab.tool}
        merged, files = get_merged(lab.project, lab.commit)

        # --- replicate build_pair's file branch to learn WHY it used file/xlsx ---
        source = "xlsx"
        cand = dev = ""
        if merged is not None:
            idx, ov = groundtruth.select_target_block(merged, lab.merged_snippet)
            rec["overlap"] = round(ov, 3)
            if ov >= 1.0:
                overlap_buckets["==1.0"] += 1
            elif ov >= 0.9:
                overlap_buckets["[0.9,1.0)"] += 1
            elif ov >= 0.5:
                overlap_buckets["[0.5,0.9)"] += 1
            else:
                overlap_buckets["<0.5"] += 1
            tool_file = files.get(data.tool_folder(lab.tool))
            child_file = files.get("child")
            if idx >= 0 and tool_file is not None and child_file is not None:
                treg, st_t = groundtruth.resolution_region(tool_file, merged, idx)
                dreg, st_d = groundtruth.resolution_region(child_file, merged, idx)
                if st_t == "ok" and st_d == "ok":
                    source, cand, dev = "file", treg or "", dreg or ""
                    if _empty(cand) and _empty(dev):
                        file_status["ok_BOTH_empty"] += 1
                    elif _empty(cand):
                        file_status["ok_cand_empty"] += 1
                    elif _empty(dev):
                        file_status["ok_dev_empty"] += 1
                    else:
                        file_status["ok_nonempty"] += 1
                else:
                    file_status[f"fallback:{st_t}/{st_d}"] += 1
                    # normalize-rescue: retry anchors on normalized text
                    if "anchor_not_unique" in (st_t, st_d):
                        rescue["anchor_fail"] += 1
                        nm = _norm(merged)
                        rt2, s_t2 = groundtruth.resolution_region(_norm(tool_file), nm, idx)
                        rd2, s_d2 = groundtruth.resolution_region(_norm(child_file), nm, idx)
                        if s_t2 == "ok" and s_d2 == "ok" and not _empty(rd2):
                            rescue["rescued"] += 1
                        else:
                            rescue["still_fail"] += 1
            else:
                file_status["fallback:no_idx_or_files"] += 1
        else:
            file_status["fallback:no_base_left_right"] += 1

        if source == "xlsx":
            cand = data.clean_xlsx_snippet(lab.tool_resolution)
            dev = data.clean_xlsx_snippet(lab.developer)
        rec["source"] = source
        rec["cand_empty"] = _empty(cand)
        rec["dev_empty"] = _empty(dev)

        # --- xlsx cell pollution (raw cells; merged_snippet used for selection even by file src) ---
        rec["ell_merged"] = _has_ellipsis(lab.merged_snippet)
        rec["ell_dev"] = _has_ellipsis(lab.developer)
        rec["ell_tool"] = _has_ellipsis(lab.tool_resolution)
        rec["hidden_merged"] = sorted(_hidden_flags(lab.merged_snippet))
        rec["hidden_dev"] = sorted(_hidden_flags(lab.developer))
        rec["hidden_tool"] = sorted(_hidden_flags(lab.tool_resolution))

        # --- cleanliness verdict (per source: which inputs actually reach the judge) ---
        if source == "file":
            clean = (not rec["cand_empty"]) and (not rec["dev_empty"])
            reason = "" if clean else "file_empty_region"
        else:  # xlsx snippets are what the judge sees
            ell = rec["ell_dev"] or rec["ell_tool"]
            clean = (not rec["cand_empty"]) and (not rec["dev_empty"]) and not ell
            reason = "xlsx_ellipsis" if ell else ("xlsx_empty" if (rec["cand_empty"] or rec["dev_empty"]) else "")
        rec["clean"] = clean
        rec["dirty_reason"] = reason

        # join verdict
        v = verdicts.get((lab.project, lab.commit, lab.tool))
        if v is not None:
            if "error" in v:
                rec["cm"] = "ERR"
            else:
                h, j = v.get("human"), v.get("judge")
                rec["cm"] = ("TP" if (j and h) else "FP" if (j and not h)
                             else "TN" if ((not j) and (not h)) else "FN")
        else:
            rec["cm"] = "not_evaluated"
        recs.append(rec)
        src_counter[source] += 1

    # ---------------------------------------------------------------- report
    out: list[str] = []

    def w(s=""):
        out.append(s)

    n = len(recs)
    w(f"=== INPUT FIDELITY HEALTH CHECK — {n} desirability (non-punt) cases ===")
    w(f"metaval joined: {mv_path}  (matched {sum(1 for r in recs if r['cm'] != 'not_evaluated')}/{n})")
    w(f"\n--- source split ---\n{dict(src_counter)}")
    w("\n--- file-source extraction status ---")
    for k, v in file_status.most_common():
        w(f"  {v:4d}  {k}")
    w(f"\n--- select_target_block overlap (file cases) ---\n{dict(overlap_buckets)}")
    w("  (note: low overlap = degraded MERGED snippet; high overlap can be ARTIFICIALLY high if the")
    w("   snippet was trimmed — fewer snippet lines -> smaller denominator.)")
    w("\n--- normalize-rescue (CRLF->LF + rstrip) on anchor_not_unique ---")
    w(f"  anchor failures: {rescue['anchor_fail']}  rescued: {rescue['rescued']}  still failing: {rescue['still_fail']}")
    w("  (rescued = was only whitespace/CRLF; still failing => likely real rename/repack.)")

    w("\n--- emptiness on FINAL built inputs ---")
    w(f"  candidate empty: {sum(r['cand_empty'] for r in recs)}   "
      f"developer empty: {sum(r['dev_empty'] for r in recs)}   "
      f"either: {sum((r['cand_empty'] or r['dev_empty']) for r in recs)}")

    w(f"\n--- xlsx ellipsis (raw cells, all {n} rows) ---")
    w(f"  merged_snippet: {sum(r['ell_merged'] for r in recs)}   "
      f"developer(child): {sum(r['ell_dev'] for r in recs)}   "
      f"tool_resolution: {sum(r['ell_tool'] for r in recs)}")
    w("\n--- hidden chars (raw cells; union of flags) ---")
    hc = Counter()
    for r in recs:
        for fl in set(r["hidden_merged"]) | set(r["hidden_dev"]) | set(r["hidden_tool"]):
            hc[fl] += 1
    w(f"  {dict(hc)}  (count = rows where that char appears in any of the 3 cells)")

    # cross: fidelity x confusion matrix
    w("\n=== CROSS: cleanliness x confusion matrix ===")
    cms = ["TP", "FP", "TN", "FN", "ERR", "not_evaluated"]

    def row(label, subset):
        c = Counter(r["cm"] for r in subset)
        w(f"  {label:22s} " + "  ".join(f"{k}={c.get(k, 0)}" for k in cms) + f"   (n={len(subset)})")

    row("ALL", recs)
    row("CLEAN", [r for r in recs if r["clean"]])
    row("DIRTY", [r for r in recs if not r["clean"]])
    w("  -- dirty broken down by reason --")
    for reason in sorted({r["dirty_reason"] for r in recs if not r["clean"]}):
        row(f"   {reason}", [r for r in recs if (not r["clean"] and r["dirty_reason"] == reason)])

    # credible confusion matrix on CLEAN subset
    clean_scored = [r for r in recs if r["clean"] and r["cm"] in ("TP", "FP", "TN", "FN")]
    cc = Counter(r["cm"] for r in clean_scored)
    tp, fp, tn, fn = cc.get("TP", 0), cc.get("FP", 0), cc.get("TN", 0), cc.get("FN", 0)
    tot = tp + fp + tn + fn
    acc = (tp + tn) / tot if tot else 0
    prec = tp / (tp + fp) if (tp + fp) else 0
    recl = tp / (tp + fn) if (tp + fn) else 0
    w(f"\n=== CREDIBLE confusion matrix (CLEAN inputs only, n={tot}) ===")
    w(f"  TP={tp} FP={fp} TN={tn} FN={fn}")
    w(f"  accuracy={acc:.1%}  precision={prec:.1%}  recall={recl:.1%}")

    out_path = Path(args.out) if args.out else (config.OUTPUT_DIR / "diag" / "fidelity_report.txt")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(out), encoding="utf-8")
    # also dump per-case records for deeper slicing
    jsonl_path = out_path.with_suffix(".jsonl")
    with open(jsonl_path, "w", encoding="utf-8") as fh:
        for r in recs:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"wrote report -> {out_path}")
    print(f"wrote per-case records -> {jsonl_path}")


if __name__ == "__main__":
    main()
