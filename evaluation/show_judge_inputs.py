"""Inspect the actual judge inputs (conflict / candidate / developer) for chosen labels.

Free (no LLM call): rebuilds each pair via conflictagent.pairs.build_judge_inputs — byte-identical
to what the DeepEval suite feeds the judge — so we can see WHY a case was a disagreement
(judge too strict, or the xlsx-fallback snippet is partial/empty).

Filter by project and/or tool; defaults to printing all desirability pairs (skip with care, large).

    python evaluation/show_judge_inputs.py --project RxJava
    python evaluation/show_judge_inputs.py --project springfox --tool FSTMerge
    python evaluation/show_judge_inputs.py --project eureka --source xlsx --max 5
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from conflictagent import data, pairs   # noqa: E402

_RULE = "-" * 78


def _show(tag: str, text: str) -> None:
    body = text if text.strip() else "  <EMPTY>"
    print(f"\n[{tag}]")
    print(body)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=None, help="substring match on project")
    ap.add_argument("--tool", default=None, help="exact xlsx tool name (FSTMerge/JDime/IntelliMerge/AutoMerge/KDIFF3)")
    ap.add_argument("--source", default=None, choices=["file", "xlsx"], help="only this extraction source")
    ap.add_argument("--max", type=int, default=10, help="cap how many pairs to print")
    args = ap.parse_args()

    labels = data.load_manual_labels()
    shown = 0
    for lab in labels:
        if lab.is_punt:
            continue
        if args.project and args.project.lower() not in lab.project.lower():
            continue
        if args.tool and lab.tool != args.tool:
            continue
        ji = pairs.build_judge_inputs(lab)
        if args.source and ji.source != args.source:
            continue
        if shown >= args.max:
            print(f"\n... stopped at --max {args.max} ...")
            break
        shown += 1
        print("\n" + "=" * 78)
        print(f"{lab.project} / {lab.tool}   source={ji.source}   human_desirable={lab.desirable}")
        print(_RULE)
        _show("CONFLICT (judge INPUT)", ji.conflict)
        _show("CANDIDATE (tool resolution = actual_output)", ji.candidate)
        _show("DEVELOPER (expected_output)", ji.developer)

    if shown == 0:
        print("No matching desirability pairs.")
    else:
        print(f"\n{_RULE}\nprinted {shown} pair(s).")


if __name__ == "__main__":
    main()
