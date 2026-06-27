"""LLM vs ConflictBench SOTA tools — both scored by the SAME ① GEval judge (apples-to-apples).

Unlike scripts/compare_tools.py (which scores under the hand-built judge), this reads the GEval ①
verdicts that already exist on disk -- no API calls, no re-judging:

  * LLM ① verdicts   <- outputs/deepeval/solver_eval_*.jsonl   (field 'accept', per scenario/provider)
  * tool ① verdicts  <- outputs/deepeval/meta_evaluation_*.jsonl (field 'judge', per project/tool)
                        [the meta-evaluation run's by-product: ① judged every tool resolution]
  * tool punts/vc    <- data.load_manual_labels()               (clean is_punt + valid_conflict)

The same instrument scored both sides on the same 3-segment input shape (conflict + candidate +
developer), so the rates are directly comparable. Caveat recorded in docs: the conflict segment's
provenance differs (LLM = reconstructed file; tools = build_judge_inputs, file-or-xlsx fallback).

Two views per conflict-type (true is the headline), under the coverage-fair OVERALL convention
(a tool that punts or has no resolution counts as a MISS, because the LLM almost always resolves):
  - among-resolved : ①-accept only over cases the method actually resolved (confounded by punt rate);
  - overall        : ①-accept over ALL comparable scenarios (punt/absent = miss) -- the fair number.

Comparable set = projects that have BOTH an LLM ① verdict and tool labels (the head-to-head subset;
the LLM-only headline set is larger and lives in run_solver_eval.py).

Run:  python scripts/compare_tools_geval.py            # newest solver_eval + meta_evaluation
      python scripts/compare_tools_geval.py --llm <f> --tool <f>
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from conflictagent import config, data  # noqa: E402

TOOLS = data.TOOLS  # ["FSTMerge","JDime","IntelliMerge","AutoMerge","KDIFF3"]


def _newest(pattern: str) -> str | None:
    hits = sorted(glob.glob(pattern), key=lambda p: Path(p).stat().st_mtime, reverse=True)
    return hits[0] if hits else None


def _find_llm(override: str | None) -> str:
    if override:
        return override
    d = str(config.OUTPUT_DIR / "deepeval")
    return _newest(f"{d}/solver_eval_*.jsonl") or sys.exit(f"no solver_eval_*.jsonl under {d}")


def _find_tool(override: str | None) -> str:
    if override:
        return override
    d = str(config.OUTPUT_DIR / "deepeval")
    return (_newest(f"{d}/meta_evaluation_*.jsonl")
            or _newest(f"{d}/metaval_*.jsonl")
            or sys.exit(f"no meta_evaluation_*.jsonl / metaval_*.jsonl under {d}"))


def _rate(hits: int, n: int) -> str:
    return f"{hits:3d}/{n:<3d} = {100 * hits / n:5.1f}%" if n else "   n/a"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", default=None, help="solver_eval_*.jsonl (LLM ① verdicts)")
    ap.add_argument("--tool", default=None, help="meta_evaluation_*.jsonl (tool ① verdicts)")
    args = ap.parse_args()

    llm_path = _find_llm(args.llm)
    tool_path = _find_tool(args.tool)
    print(f"llm  (① on solvers): {llm_path}")
    print(f"tool (① on tools)  : {tool_path}")

    # --- LLM ① accept, per (provider, project); project = scenario key (id before '@') ---
    llm: dict[str, dict[str, bool]] = defaultdict(dict)   # provider -> {project: accept}
    vc_of: dict[str, bool | None] = {}                    # project -> valid_conflict
    for line in open(llm_path, encoding="utf-8"):
        if not line.strip():
            continue
        r = json.loads(line)
        if "error" in r or "accept" not in r:
            continue
        proj = r["id"].split("@")[0]
        llm[r["provider"]][proj] = bool(r["accept"])
        vc_of[proj] = r.get("valid_conflict")
    providers = sorted(llm)
    if not providers:
        sys.exit("no usable LLM ① records")

    # --- tool ① verdict, per (project, tool) [only NON-PUNT, judgeable resolutions were judged] ---
    tool_judge: dict[tuple[str, str], bool] = {}
    for line in open(tool_path, encoding="utf-8"):
        if not line.strip():
            continue
        r = json.loads(line)
        if "error" in r or r.get("judge") is None:
            continue
        tool_judge[(r["project"], r["tool"])] = bool(r["judge"])

    # --- tool punt + label presence, from the data layer (clean is_punt + 4 file-verified overrides) ---
    punt: dict[tuple[str, str], bool] = {}
    for lab in data.load_manual_labels():
        punt[(lab.project, lab.tool)] = lab.is_punt

    # --- comparable set: projects with an LLM ① verdict AND at least one tool label, by conflict type ---
    llm_projects = set(vc_of)
    tool_projects = {p for (p, _t) in tool_judge} | {p for (p, _t) in punt}
    comparable = llm_projects & tool_projects
    true_set = sorted(p for p in comparable if vc_of[p] is True)
    false_set = sorted(p for p in comparable if vc_of[p] is False)
    print(f"\ncomparable projects (LLM ① ∩ tool labels): {len(comparable)}  "
          f"-> TRUE {len(true_set)} | FALSE {len(false_set)}")
    print(f"  (LLM-only, no tool labels: {len(llm_projects - tool_projects)}; "
          f"tool-only, no LLM ①: {len(tool_projects - llm_projects)})")

    def tool_cell(tool: str, subset: list[str]) -> tuple[int, int, int, int]:
        """Return (hits, resolved, punts, absent) for a tool over a project subset.

        resolved = has an ① verdict (non-punt, judgeable); hits = of those, ①-accept.
        punts    = is_punt True (tool left the conflict unresolved).
        absent   = no ① verdict and not a punt (no label, or empty-region drop) -> miss under overall.
        """
        hits = resolved = punts = absent = 0
        for p in subset:
            if punt.get((p, tool)) is True:
                punts += 1
            elif (p, tool) in tool_judge:
                resolved += 1
                hits += 1 if tool_judge[(p, tool)] else 0
            else:
                absent += 1
        return hits, resolved, punts, absent

    def report(name: str, subset: list[str]) -> None:
        n = len(subset)
        print(f"\n===== {name} (n={n}) =====")
        print(f"  {'solver / tool':<14}{'among-resolved':>18}{'overall':>18}{'punt':>6}{'absent':>8}")
        rows = []
        for prov in providers:                         # LLM: resolves ~all; among-resolved == overall
            res = [p for p in subset if p in llm[prov]]
            hits = sum(1 for p in res if llm[prov][p])
            rows.append((f"LLM {prov}", hits, len(res), hits, n, 0, n - len(res)))
        for t in TOOLS:
            hits, resolved, punts, absent = tool_cell(t, subset)
            rows.append((t, hits, resolved, hits, n, punts, absent))
        rows.sort(key=lambda x: (x[3] / x[4] if x[4] else 0), reverse=True)  # rank by overall
        for label, ar_h, ar_n, ov_h, ov_n, punts, absent in rows:
            print(f"  {label:<14}{_rate(ar_h, ar_n):>18}{_rate(ov_h, ov_n):>18}"
                  f"{punts:>6}{absent:>8}")

    report("TRUE conflicts (genuine semantic divergence)", true_set)
    report("FALSE conflicts (compatible / non-overlapping edits)", false_set)

    # --- headline: true conflicts, overall convention, LLM vs the strongest tool ---
    print("\n===== HEADLINE: TRUE conflicts, overall convention (① judge, coverage-fair) =====")
    n = len(true_set)
    for prov in providers:
        h = sum(1 for p in true_set if llm[prov].get(p))
        print(f"  LLM {prov:<10} {_rate(h, n)}")
    best, best_h = None, -1
    for t in TOOLS:
        h, _r, _p, _a = tool_cell(t, true_set)
        if h > best_h:
            best, best_h = t, h
    print(f"  best tool ({best}): {_rate(best_h, n)}")
    print("\nNote: OVERALL convention (punt / no-resolution = miss) is the fair metric when tools "
          "selectively abstain;\namong-resolved is shown only as context (a tool that punts the hard "
          "cases looks inflated there).")


if __name__ == "__main__":
    main()
