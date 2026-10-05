"""Recompute the reported ConflictAgent numbers from the frozen results in results/.

No API key, no LLM calls, standard library only:

    python scripts/verify_numbers.py

Each figure is recomputed from the per-case files and compared with the value quoted in README.md and
docs/RESULTS.md (those quoted values are kept in EXPECTED below; change both together). Before that,
the files are checked against their committed sha256, for duplicate rows, and for verdicts that
disagree with their scores at the 0.5 threshold. The script exits with status 1 if any check fails. The LLM-vs-tools table also needs the
ConflictBench labels (which tool outputs were left unresolved); see docs/REPRODUCE.md.
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JUDGE_FILE = ROOT / "results" / "meta_evaluation_20260727_062930.jsonl"
SOLVER_FILE = ROOT / "results" / "solver_eval_20260627_095221.jsonl"

# Values as quoted in README.md / docs/RESULTS.md.
EXPECTED = {
    "judge: labeled cases": "292",
    "judge: TP / FP / TN / FN": "117 / 0 / 111 / 64",
    "judge: precision": "100.0%",
    "judge: recall": "64.6%",
    "judge: accuracy": "78.1%",
    "solver: records (scenario x provider)": "132",
    "solver dev-match, true, openai": "27/49 = 55.1%",
    "solver dev-match, true, gemini": "29/47 = 61.7%",
    "solver dev-match, true, floor (reported)": "55.1%",
    "solver dev-match, true, pooled": "56/96 = 58.3%",
    "solver dev-match, false, openai": "12/18 = 66.7%",
    "solver dev-match, false, gemini": "11/18 = 61.1%",
    "structural validity, true": "92/96 = 95.8%",
    "structural validity, false": "35/36 = 97.2%",
    "structural failures accepted by judge (1)": "4 of 5",
}
THRESHOLD = 0.5  # GEval score -> verdict cutoff used for both runs (score >= threshold = accept)
BOUNDARY = 1e-3  # stored scores are rounded; verdicts this close to the cutoff are not re-checked
SHA256 = {  # the frozen files as committed; a mismatch means they were changed after publication
    "meta_evaluation_20260727_062930.jsonl": "1c2f64a3d63bf21e072c9ebee952bd36faca934383fca5e2e6572968c1ba1a8f",
    "solver_eval_20260627_095221.jsonl": "f03a9219fdb4f58222538f43937b88f269abd6d908eff0e277725f550bc2fd36",
}


def _load(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _frac(a: int, n: int) -> str:
    return f"{a}/{n} = {a / n:.1%}"


def recompute() -> dict[str, str]:
    got: dict[str, str] = {}

    judge = _load(JUDGE_FILE)
    tp = sum(1 for r in judge if r["judge"] and r["human"])
    fp = sum(1 for r in judge if r["judge"] and not r["human"])
    tn = sum(1 for r in judge if not r["judge"] and not r["human"])
    fn = sum(1 for r in judge if not r["judge"] and r["human"])
    got["judge: labeled cases"] = str(len(judge))
    got["judge: TP / FP / TN / FN"] = f"{tp} / {fp} / {tn} / {fn}"
    got["judge: precision"] = f"{tp / (tp + fp):.1%}"
    got["judge: recall"] = f"{tp / (tp + fn):.1%}"
    got["judge: accuracy"] = f"{(tp + tn) / len(judge):.1%}"

    solver = _load(SOLVER_FILE)
    got["solver: records (scenario x provider)"] = str(len(solver))
    true_rate = []
    for conflict, label in ((True, "true"), (False, "false")):
        rows = [r for r in solver if r["valid_conflict"] is conflict]
        for provider in ("openai", "gemini"):
            sub = [r for r in rows if r["provider"] == provider]
            hits = sum(1 for r in sub if r["accept"])
            got[f"solver dev-match, {label}, {provider}"] = _frac(hits, len(sub))
            if conflict:
                true_rate.append(hits / len(sub))
        if conflict:
            got["solver dev-match, true, floor (reported)"] = f"{min(true_rate):.1%}"
            got["solver dev-match, true, pooled"] = _frac(sum(1 for r in rows if r["accept"]), len(rows))
        got[f"structural validity, {label}"] = _frac(sum(1 for r in rows if r["structurally_valid"]), len(rows))
    invalid = [r for r in solver if not r["structurally_valid"]]
    got["structural failures accepted by judge (1)"] = f"{sum(1 for r in invalid if r['accept'])} of {len(invalid)}"
    return got


def integrity_problems() -> list[str]:
    """Checks that would otherwise let wrong data pass silently."""
    problems = []
    judge, solver = _load(JUDGE_FILE), _load(SOLVER_FILE)
    for name, rows, key, verdict, score in (
        (JUDGE_FILE.name, judge, ("project", "commit", "tool"), "judge", "score"),
        (SOLVER_FILE.name, solver, ("id", "provider"), "accept", "accept_score"),
    ):
        dups = [k for k, n in Counter(tuple(r[f] for f in key) for r in rows).items() if n > 1]
        if dups:
            problems.append(f"{name}: {len(dups)} duplicate rows, e.g. {dups[0]}")
        off = [r for r in rows
               if abs(r[score] - THRESHOLD) >= BOUNDARY and bool(r[verdict]) != (r[score] >= THRESHOLD)]
        if off:
            problems.append(f"{name}: {len(off)} verdicts disagree with score >= {THRESHOLD}")
    return problems


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    problems = integrity_problems()
    for path in (JUDGE_FILE, SOLVER_FILE):
        digest = sha256(path)
        print(f"{path.relative_to(ROOT)}  sha256 {digest[:16]}")
        if digest != SHA256[path.name]:
            problems.append(f"{path.name}: sha256 differs from the committed file")
    for p in problems:
        print(f"INTEGRITY: {p}")
    print()
    got = recompute()
    width = max(len(k) for k in EXPECTED)
    bad = 0
    print(f"{'figure':<{width}}  {'recomputed':<20}  {'reported':<20}")
    for key, want in EXPECTED.items():
        have = got.get(key, "(missing)")
        ok = have == want
        bad += not ok
        print(f"{key:<{width}}  {have:<20}  {want:<20}  {'ok' if ok else 'MISMATCH'}")
    print(f"\n{len(EXPECTED) - bad}/{len(EXPECTED)} figures match; {len(problems)} integrity problems.")
    return 1 if bad or problems else 0


if __name__ == "__main__":
    sys.exit(main())
