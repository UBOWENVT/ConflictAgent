"""Quantify the 'ok + empty dev_region' hole for the SOLVER line (Dataset B prep).

The solver comparable set gates on dev_status=='ok'. But resolution_region can return status 'ok'
with an EMPTY region (anchors matched uniquely, 0 lines between them -- e.g. developer reordered
the block). Those slip past the gate and the solver gets judged against an empty expected_output
(an unfair dev_match=False). This counts how many of the 93 reconstructable Java scenarios that
happens on, stratified by valid_conflict (true/false), since the headline is the true-conflict row.

No LLM calls. Writes a short report.

    python evaluation/audit_solver_devregion.py
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from conflictagent import config, data, groundtruth, merge, validate   # noqa: E402


def _empty(s) -> bool:
    return not (s or "").strip()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    out: list[str] = []

    def w(s=""):
        out.append(s)

    # same population as run_eval.py: reconstructable Java scenarios
    usable = []
    for s in data.load_scenarios(java_only=True):
        fv = data.load_full_versions(s)
        if fv:
            usable.append((s, fv))

    status_counter = Counter()                  # overall dev_region status
    empty_by_vc = {True: 0, False: 0, None: 0}  # ok+empty, stratified by valid_conflict
    ok_nonempty_by_vc = {True: 0, False: 0, None: 0}
    empty_examples = []

    for s, fv in usable:
        merged, _ = merge.reconstruct_merged(fv["base"], fv["left"], fv["right"])
        blocks = validate.conflict_blocks(merged)
        tgt, _ = groundtruth.select_target_block(merged, s.conflict_chunk)
        if tgt < 0 or tgt >= len(blocks):
            status_counter["no_block"] += 1
            continue
        if "child" not in fv:
            status_counter["no_child"] += 1
            continue
        region, st = groundtruth.resolution_region(fv["child"], merged, tgt)
        if st != "ok":
            status_counter[f"not_ok:{st}"] += 1
            continue
        if _empty(region):
            status_counter["ok_EMPTY"] += 1
            empty_by_vc[s.valid_conflict] += 1
            if len(empty_examples) < 12:
                empty_examples.append(f"{s.id}  (valid_conflict={s.valid_conflict})")
        else:
            status_counter["ok_nonempty"] += 1
            ok_nonempty_by_vc[s.valid_conflict] += 1

    w(f"=== SOLVER dev_region audit — {len(usable)} reconstructable Java scenarios ===\n")
    w("--- dev_region extraction status (per scenario, target block) ---")
    for k, v in status_counter.most_common():
        w(f"  {v:4d}  {k}")

    ok_empty = status_counter.get("ok_EMPTY", 0)
    ok_ne = status_counter.get("ok_nonempty", 0)
    gated_in = ok_empty + ok_ne  # what passes dev_status=='ok'
    w("\n--- the hole ---")
    w(f"  pass dev_status=='ok' gate : {gated_in}")
    w(f"    of which ok+EMPTY (slip through, unfair to solver): {ok_empty}")
    w(f"    of which ok+nonempty (genuinely gradeable)        : {ok_ne}")
    if gated_in:
        w(f"    -> {ok_empty}/{gated_in} = {ok_empty / gated_in:.1%} of the gated set is the empty hole")
    w(f"\n  ok+EMPTY by conflict type (headline = true): "
      f"true={empty_by_vc[True]}  false={empty_by_vc[False]}  unknown={empty_by_vc[None]}")
    w(f"  ok+nonempty by conflict type:                "
      f"true={ok_nonempty_by_vc[True]}  false={ok_nonempty_by_vc[False]}  unknown={ok_nonempty_by_vc[None]}")
    w("\n--- ok+EMPTY examples ---")
    for e in empty_examples:
        w(f"  {e}")

    out_path = Path(args.out) if args.out else (config.OUTPUT_DIR / "diag" / "solver_devregion_audit.txt")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(out), encoding="utf-8")
    print(f"wrote report -> {out_path}")


if __name__ == "__main__":
    main()
