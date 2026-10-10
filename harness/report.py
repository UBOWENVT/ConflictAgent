"""Result tables from the unified scoring output (evaluation/run_unified_eval.py).

    python -m harness.report outputs/deepeval/unified_eval_X.jsonl \\
        [--frozen results/solver_eval_20260627_095221.jsonl] [--csv per_sample.csv]

Everything is counted from the verdict rows, with the outcome rules of harness/scorers.py:
  primary    a sample counts as accepted only if its outcome is `gradeable` and the judge
             accepted it; every other outcome is a miss. Denominators are fixed: 49 true and
             18 false conflicts per model.
  secondary  OUTCOME_RULES[outcome][1]: `judge` uses the verdict (out_of_block: on the in-block
             region), `miss` counts as not accepted, `exclude` leaves the denominator.
The headline is the lower of the two providers, never a pooled rate. Every table also shows the
rates without presto@f50b46c7 (reconstructed block spans two real conflicts; (2) false positive,
see docs/HARNESS.md).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from math import comb
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.scorers import OUTCOME_RULES  # noqa: E402

PRESTO = "presto@f50b46c7"
N_TYPE = {True: 49, False: 18}


def load(path: str) -> tuple[dict, list[dict]]:
    meta, rows = {}, []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r["kind"] == "_meta":
            meta = r
        elif r["kind"] == "verdict":
            rows.append(r)
    missing = [r for r in rows if r["judged"] and r.get("accept") is None]
    if missing:
        raise SystemExit(f"{len(missing)} judged rows have no verdict (judge errors?): rerun with "
                         f"--resume first, e.g. {[(r['group'], r['id'], r['provider']) for r in missing[:3]]}")
    return meta, rows


def primary_hit(r: dict) -> bool:
    return r["outcome"] == "gradeable" and r.get("accept") is True


def secondary(r: dict) -> bool | None:
    """True / False for counted rows, None when excluded."""
    rule = OUTCOME_RULES.get(r["outcome"], ("miss", "exclude"))[1]
    if rule == "exclude":
        return None
    if rule == "miss":
        return False
    return r.get("accept") is True


def rate(k: int, n: int) -> str:
    return f"{k}/{n} = {k / n:.1%}" if n else "n/a"


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value from the discordant counts."""
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(comb(n, k) for k in range(min(b, c) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def table(rows: list[dict], groups: list[str], drop_presto: bool = False) -> list[str]:
    out = ["| group | provider | type | primary | secondary |", "|---|---|---|---|---|"]
    for g in groups:
        for prov in sorted({r["provider"] for r in rows if r["group"] == g}):
            for vc in (True, False):
                rs = [r for r in rows if r["group"] == g and r["provider"] == prov
                      and r["valid_conflict"] is vc and not (drop_presto and r["id"] == PRESTO)]
                n = N_TYPE[vc] - (1 if drop_presto and vc else 0)
                p = sum(primary_hit(r) for r in rs)
                sec = [secondary(r) for r in rs]
                counted = [x for x in sec if x is not None]
                out.append(f"| {g} | {prov} | {'true' if vc else 'false'} | {rate(p, n)} | "
                           f"{rate(sum(counted), len(counted))} |")
    return out


def headline(rows: list[dict], group: str, drop_presto: bool = False) -> str:
    per = []
    for prov in sorted({r["provider"] for r in rows if r["group"] == group}):
        rs = [r for r in rows if r["group"] == group and r["provider"] == prov
              and r["valid_conflict"] is True and not (drop_presto and r["id"] == PRESTO)]
        n = N_TYPE[True] - (1 if drop_presto else 0)
        per.append((sum(primary_hit(r) for r in rs) / n, prov, sum(primary_hit(r) for r in rs), n))
    low = min(per)
    return f"{group}: lower provider {low[1]} {rate(low[2], low[3])}"


def structural(rows: list[dict], groups: list[str]) -> list[str]:
    out = ["| group | provider | (2) true conflicts | (2) without presto |", "|---|---|---|---|"]
    for g in groups:
        for prov in sorted({r["provider"] for r in rows if r["group"] == g}):
            rs = [r for r in rows if r["group"] == g and r["provider"] == prov
                  and r["valid_conflict"] is True and r["structurally_valid"] is not None]
            rs2 = [r for r in rs if r["id"] != PRESTO]
            out.append(f"| {g} | {prov} | {rate(sum(r['structurally_valid'] for r in rs), len(rs))}"
                       f" | {rate(sum(r['structurally_valid'] for r in rs2), len(rs2))} |")
    return out


def paired(rows: list[dict], a: str, b: str, drop_presto: bool = False) -> list[str]:
    """Per-scenario pairing of two groups on true conflicts, primary convention."""
    out = [f"| provider | both | only {a} | only {b} | neither | McNemar exact p |",
           "|---|---|---|---|---|---|"]
    for prov in sorted({r["provider"] for r in rows if r["group"] == a}):
        ga = {r["id"]: primary_hit(r) for r in rows if r["group"] == a and r["provider"] == prov
              and r["valid_conflict"] is True}
        gb = {r["id"]: primary_hit(r) for r in rows if r["group"] == b and r["provider"] == prov
              and r["valid_conflict"] is True}
        ids = sorted(set(ga) | set(gb))
        if drop_presto:
            ids = [i for i in ids if i != PRESTO]
        both = sum(ga.get(i, False) and gb.get(i, False) for i in ids)
        only_a = sum(ga.get(i, False) and not gb.get(i, False) for i in ids)
        only_b = sum(gb.get(i, False) and not ga.get(i, False) for i in ids)
        neither = len(ids) - both - only_a - only_b
        out.append(f"| {prov} | {both} | {only_a} | {only_b} | {neither} | "
                   f"{mcnemar_exact(only_a, only_b):.3f} |")
    return out


def drift(rows: list[dict], frozen_path: str, group: str = "june") -> list[str]:
    frozen = {(r["id"], r["provider"]): r["accept"]
              for r in (json.loads(line) for line in Path(frozen_path).read_text().splitlines()
                        if line.strip())}
    now = {(r["id"], r["provider"]): r.get("accept") for r in rows
           if r["group"] == group and r["judged"]}
    keys = sorted(set(frozen) & set(now))
    flips = [k for k in keys if frozen[k] != now[k]]
    lines = [f"judge drift: {len(keys) - len(flips)}/{len(keys)} June verdicts reproduced; "
             f"{len(flips)} flipped"]
    lines += [f"  {k[0]} {k[1]}: June {frozen[k]} -> now {now[k]}" for k in flips]
    return lines


def gate(rows: list[dict], group: str = "agent") -> list[str]:
    rs = [r for r in rows if r["group"] == group]
    n = len(rs)
    lines = [f"day-4 gate ({group}, {n} samples; each must be <= 10%):"]
    for o in ("not_extractable", "out_of_block", "unfinished"):
        k = sum(r["outcome"] == o for r in rs)
        lines.append(f"  {o}: {rate(k, n)}")
    return lines


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("unified")
    ap.add_argument("--frozen", default="results/solver_eval_20260627_095221.jsonl")
    ap.add_argument("--agent", default="agent")
    ap.add_argument("--single-shot", default="single_shot")
    ap.add_argument("--csv", default=None)
    args = ap.parse_args()
    meta, rows = load(args.unified)
    groups = list(meta.get("groups", {})) or sorted({r["group"] for r in rows})
    print(f"judge {meta.get('judge')} threshold {meta.get('threshold')} deepeval "
          f"{meta.get('deepeval')}; groups {groups}\n")
    print("## (1) developer-match\n")
    print("\n".join(table(rows, groups)))
    print("\nwithout presto:\n")
    print("\n".join(table(rows, groups, drop_presto=True)))
    print()
    for g in groups:
        print(headline(rows, g), "|", headline(rows, g, drop_presto=True).split(": ", 1)[1],
              "(without presto)")
    print("\n## (2) structural validity\n")
    print("\n".join(structural(rows, groups)))
    if args.agent in groups and args.single_shot in groups:
        print(f"\n## paired: {args.agent} vs {args.single_shot} (true conflicts, primary)\n")
        print("\n".join(paired(rows, args.agent, args.single_shot)))
        print("\nwithout presto:\n")
        print("\n".join(paired(rows, args.agent, args.single_shot, drop_presto=True)))
    if "june" in groups:
        print("\n## drift\n")
        print("\n".join(drift(rows, args.frozen)))
        if args.single_shot in groups:
            print(f"\nmodel drift ({args.single_shot} vs june, primary, true conflicts):\n")
            print("\n".join(paired(rows, args.single_shot, "june")))
    if args.agent in groups:
        print("\n" + "\n".join(gate(rows, args.agent)))
    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as fh:
            keys = ["group", "id", "provider", "model", "valid_conflict", "outcome", "judged",
                    "accept", "accept_score", "structurally_valid"]
            w = csv.DictWriter(fh, fieldnames=keys + ["primary", "secondary"],
                               extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow({**r, "primary": primary_hit(r), "secondary": secondary(r)})
        print(f"\nper-sample rows -> {args.csv}")


if __name__ == "__main__":
    main()
