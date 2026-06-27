"""Merge all Scheme-A solver runs into one deduplicated complete set for Dataset B.

Scans outputs/eval/runs/eval_A_*.jsonl (the main run + targeted re-runs), keeps ONE record per
(id, provider), preferring a non-empty final_resolution over empty/error (so a good re-run wins
over an early empty-resolution-bug record or a 503 failure). Restricts to the COMPARABLE set:
scenarios whose developer region extracted (dev_status == 'ok'); the rest (anchor_not_unique /
no_block) have no gradeable ground truth and are excluded.

Writes outputs/eval/eval_A_complete.jsonl + prints a completeness table.

    python evaluation/build_complete_set.py
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from conflictagent import config   # noqa: E402

PROVIDERS = ("openai", "gemini")


def _rank(rec: dict) -> int:
    """Higher = better record to keep for a given (id, provider)."""
    if (rec.get("final_resolution") or "").strip():
        return 3                      # a real, non-empty resolution
    if rec.get("status") == "empty":
        return 2                      # honest non-result (model returned nothing)
    if "error" in rec:
        return 1                      # transient failure (e.g. 503)
    return 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval-dir", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    eval_dir = Path(args.eval_dir) if args.eval_dir else config.OUTPUT_DIR / "eval" / "runs"
    out_path = Path(args.out) if args.out else eval_dir.parent / "eval_A_complete.jsonl"

    files = sorted(p for p in eval_dir.glob("eval_A_*.jsonl")
                   if p.name != out_path.name and "complete" not in p.name)

    dev_status: dict[str, str] = {}      # id -> dev_status (scenario property, deterministic)
    best: dict[tuple, dict] = {}         # (id, provider) -> best record seen
    for f in files:
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("kind") != "llm":
                continue
            sid, prov = r.get("id"), r.get("provider")
            ds = r.get("dev_status")
            if ds is not None:
                dev_status.setdefault(sid, ds)
            key = (sid, prov)
            if key not in best or _rank(r) > _rank(best[key]):
                best[key] = r

    comparable = sorted(i for i, ds in dev_status.items() if ds == "ok")

    # assemble complete set: best record per (comparable id, provider)
    out_records = []
    table = {p: Counter() for p in PROVIDERS}
    missing = {p: [] for p in PROVIDERS}
    for sid in comparable:
        for prov in PROVIDERS:
            rec = best.get((sid, prov))
            if rec is None:
                table[prov]["MISSING"] += 1
                missing[prov].append(sid)
                continue
            out_records.append(rec)
            if (rec.get("final_resolution") or "").strip():
                table[prov]["has_resolution"] += 1
            elif rec.get("status") == "empty":
                table[prov]["empty"] += 1
            elif "error" in rec:
                table[prov]["error"] += 1
            else:
                table[prov]["other"] += 1

    # provenance header (first line):固定名 complete set 不带时间戳，溯源信息跟着数据走 ——
    # generated_at + which run files it came from + completeness, so the file self-documents
    # what it is without a timestamped filename. Readers must skip records where kind == '_meta'.
    meta = {
        "kind": "_meta",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scheme": "A",
        "n_comparable_scenarios": len(comparable),
        "n_records": len(out_records),
        "completeness": {p: dict(table[p]) for p in PROVIDERS},
        "source_runs": [f.name for f in files],
    }

    out_path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in ([meta] + out_records)) + "\n",
        encoding="utf-8")

    # report
    print(f"scanned {len(files)} eval_A_*.jsonl files")
    print(f"comparable scenarios (dev_status=ok): {len(comparable)}")
    print(f"excluded (anchor_not_unique / no_block): "
          f"{sum(1 for ds in dev_status.values() if ds != 'ok')}")
    print(f"\n=== completeness over {len(comparable)} comparable scenarios x 2 providers ===")
    for p in PROVIDERS:
        t = table[p]
        print(f"  {p:7}: has_resolution={t['has_resolution']}  empty={t['empty']}  "
              f"error={t['error']}  other={t['other']}  MISSING={t['MISSING']}")
        if missing[p]:
            print(f"           MISSING ids: {missing[p]}")
        if t["empty"]:
            empties = [sid for sid in comparable
                       if (best.get((sid, p)) or {}).get("status") == "empty"]
            print(f"           empty ids:   {empties}")
        if t["error"]:
            errs = [sid for sid in comparable
                    if best.get((sid, p)) and "error" in best[(sid, p)]]
            print(f"           error ids:   {errs}")
    print(f"\nwrote {len(out_records)} records -> {out_path}")


if __name__ == "__main__":
    main()
