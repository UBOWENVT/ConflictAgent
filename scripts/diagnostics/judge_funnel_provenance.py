#!/usr/bin/env python3
"""Judge-line provenance: emit a per-point CSV explaining the 900 -> 292 funnel.

Reproduces the exact staging that ``evaluation/dataset.build_metaevaluation_testcases`` applies,
one row per (scenario-row x tool) pair (900 total), tagging each with the stage at which it
leaves the funnel:

  no_label      tool has no 0/1 desirability label             (excluded from the 627 labeled pairs)
  punt          tool left the conflict unresolved (is_punt)    -- a detection event, not a resolution
  file_level_B  scenario has no complete base/left/right 3-way -- add/delete/rename; conflict ill-defined
  empty_region  candidate or developer region came out empty   -- nothing to judge (GEval rejects empty)
  KEPT          fed to the GEval judge                         (n = 292)

Funnel:  900 -(273 no_label)-> 627 -(253 punt)-> 374 -(22 file_level_B)-> 352 -(60 empty)-> 292

This is a diagnostics/audit script: it deliberately reaches into ``conflictagent.data`` internals
so the enumeration matches ``load_manual_labels`` exactly (which drops no-label pairs). The KEPT
set here is identical, point for point, to what the DeepEval suite scores.

Run:
    python scripts/diagnostics/judge_funnel_provenance.py                 # writes outputs/judge_funnel_900.csv
    python scripts/diagnostics/judge_funnel_provenance.py -o path.csv

Exits non-zero if the stage counts drift from the expected funnel (a regression guard).
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from conflictagent import data, pairs                                    # noqa: E402
from conflictagent.data import (                                         # noqa: E402
    ManualLabel, TOOLS, _load_gold_df, _tool_columns, _b, _s,
    _C_PROJECT, _C_COMMIT, _C_VALID, _C_CHILD, _C_MERGED, _C_FILETYPE,
)

EXPECTED = {"no_label": 273, "punt": 253, "file_level_B": 22, "empty_region": 60, "KEPT": 292}
STAGES = ["no_label", "punt", "file_level_B", "empty_region", "KEPT"]
FIELDS = ["project", "commit", "tool", "file_type", "valid_conflict",
          "has_3way", "source", "human_desirable", "stage", "detail"]


def build_rows() -> list[dict]:
    df = _load_gold_df()
    _three_way: dict[tuple[str, str], bool] = {}

    def has_3way(project: str, commit: str) -> bool:
        key = (project, commit)
        if key not in _three_way:
            files = data.load_scenario_files(project, commit)
            _three_way[key] = {"base", "left", "right"} <= files.keys()
        return _three_way[key]

    rows: list[dict] = []
    for _, r in df.iterrows():
        proj, commit = _s(r[_C_PROJECT]), _s(r[_C_COMMIT])
        dev, merged = _s(r[_C_CHILD]), _s(r[_C_MERGED])
        vc = _b(r[_C_VALID])
        ftype = _s(r[_C_FILETYPE])
        for tool in TOOLS:
            _, desc_col, snip_col = _tool_columns(tool)
            label = _b(r[desc_col])
            strat = _s(r[f"{tool} Strategy"])
            row = {"project": proj, "commit": commit, "tool": tool, "file_type": ftype,
                   "valid_conflict": vc, "has_3way": "", "source": "",
                   "human_desirable": "", "stage": "", "detail": ""}

            # (0) no 0/1 desirability label -> never enters load_manual_labels' 627.
            if label is None:
                row.update(stage="no_label", detail="tool has no 0/1 desirability (N/A)")
                rows.append(row)
                continue

            lab = ManualLabel(proj, commit, tool, _s(r[snip_col]), dev, merged, label, vc, strat)
            row["human_desirable"] = label

            # (1) punt: tool left the conflict unresolved -- detection, not a resolution.
            if lab.is_punt:
                row.update(stage="punt", detail=f"still conflict / detection (strategy={strat})")
                rows.append(row)
                continue

            # (2) file-level scenario: no complete 3-way -> conflict ill-defined (Scheme A gate).
            h3 = has_3way(proj, commit)
            row["has_3way"] = h3
            if not h3:
                row.update(stage="file_level_B",
                           detail="no complete base/left/right 3-way (add/delete/rename)")
                rows.append(row)
                continue

            # (3) judgeability: empty candidate or developer region -> nothing to compare.
            ji = pairs.build_judge_inputs(lab)
            row["source"] = ji.source
            if not ji.candidate.strip() or not ji.developer.strip():
                which = "candidate" if not ji.candidate.strip() else "developer"
                row.update(stage="empty_region", detail=f"empty {which} region")
                rows.append(row)
                continue

            row.update(stage="KEPT", detail="fed to GEval judge")
            rows.append(row)
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-o", "--out", default="outputs/judge_funnel_900.csv",
                    help="CSV output path (default: outputs/judge_funnel_900.csv)")
    args = ap.parse_args()

    rows = build_rows()
    counts = Counter(r["stage"] for r in rows)

    print(f"total pairs: {len(rows)}")
    ok = len(rows) == 900
    for stage in STAGES:
        got, exp = counts.get(stage, 0), EXPECTED[stage]
        flag = "OK" if got == exp else "*** MISMATCH ***"
        ok = ok and got == exp
        print(f"  {stage:14s} {got:4d}  (expected {exp:4d})  {flag}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {out}  ({len(rows)} rows)")

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
