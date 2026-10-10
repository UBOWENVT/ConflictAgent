"""Unified offline scoring: several groups of solver resolutions, ONE judge instance, ONE run.

Each group is a JSONL in scripts/run_eval.py's record schema: harness agent exports
(harness/export.py), single-shot reruns (scripts/run_eval.py --no-judge), or the June complete set
(outputs/eval/eval_A_complete.jsonl). Every group goes through
evaluation.dataset.build_solver_testcases unchanged, so input / expected_output are built exactly
as for Dataset B, and every group's input and expected_output are checked byte-for-byte against the
reference group before any judge call.

All judged cases share one GEval instance: its evaluation steps are generated once (on the first
case), written to the output, and reused for every other case and on --resume. Cases are judged
in a seeded shuffled order so no group is judged in a block.

What gets judged:
  - the reference group (default `june`): every case, exactly as run_solver_eval.py judged them,
    so its verdicts can be compared with the frozen ones (judge drift);
  - other groups: only the outcomes OUTCOME_RULES sends to the judge (gradeable; out_of_block for
    the secondary convention). Records without an `outcome` (single-shot runs) are classified
    with the same rules: error / empty / markers / gradeable.
(2) structural validity is computed for every record with a non-empty resolution.

    python -m evaluation.run_unified_eval --group agent=outputs/stage3/agent.jsonl \\
        --group june=outputs/eval/eval_A_complete.jsonl --dry-run      # no API calls
    python -m evaluation.run_unified_eval --group ... --out outputs/deepeval/unified_X.jsonl
    python -m evaluation.run_unified_eval --group ... --resume outputs/deepeval/unified_X.jsonl
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import random
import sys
import time
from collections import Counter
from importlib import metadata as importlib_metadata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from conflictagent import config, validate             # noqa: E402
from conflictagent.logging_setup import setup_logging  # noqa: E402
from evaluation import dataset, metrics                # noqa: E402

log = logging.getLogger(__name__)

JUDGED_OUTCOMES = {"gradeable", "out_of_block"}   # harness/scorers.py OUTCOME_RULES, "judge"


def classify(rec: dict) -> str:
    """Outcome of one record; harness exports carry theirs, single-shot records get the same
    rules applied here."""
    if rec.get("outcome"):
        return rec["outcome"]
    if rec.get("error"):
        return "error"
    resolution = rec.get("final_resolution") or ""
    if not resolution.strip():
        return "empty"
    if validate.has_conflict_markers(resolution):
        return "markers"
    return "gradeable"


def read_records(path: Path) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            if rec.get("kind") != "_meta":
                out.append(rec)
    return out


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_group(name: str, path: Path) -> tuple[list[dict], dict]:
    """(records, {(id, provider): LLMTestCase}) for one group."""
    records = read_records(path)
    keys = [(r.get("id"), r.get("provider")) for r in records]
    dup = [k for k, n in Counter(keys).items() if n > 1]
    if dup:
        raise SystemExit(f"group {name}: duplicate (id, provider) records: {dup[:5]}")
    cases = {(c.metadata["id"], c.metadata["provider"]): c
             for c in dataset.build_solver_testcases(path)}
    return records, cases


def check_against_reference(name: str, cases: dict, ref_cases: dict) -> int:
    """Hard check: same scenario -> byte-identical input and expected_output. Returns the number of
    cases checked; exits on any mismatch."""
    ref_by_id = {}
    for (sid, _), c in ref_cases.items():
        ref_by_id.setdefault(sid, c)
    bad, checked = [], 0
    for (sid, prov), c in cases.items():
        ref = ref_by_id.get(sid)
        if ref is None:
            continue
        checked += 1
        if c.input != ref.input or c.expected_output != ref.expected_output:
            bad.append((sid, prov, "input" if c.input != ref.input else "expected_output"))
    if bad:
        raise SystemExit(f"group {name}: test cases differ from the reference group: {bad[:5]}")
    return checked


def structural(case) -> tuple[bool | None, str]:
    if case is None:
        return None, "no resolution"
    m = metrics.StructuralValidity()
    m.measure(case)
    return bool(m.success), m.reason


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--group", action="append", required=True, metavar="NAME=PATH")
    ap.add_argument("--reference", default="june",
                    help="group whose cases define input/expected_output (judged in full)")
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true", help="build and check only; no judge calls")
    ap.add_argument("--out", default=None)
    ap.add_argument("--resume", default=None, help="continue an interrupted output file")
    args = ap.parse_args()
    setup_logging(tag="unified_eval")

    groups: dict[str, Path] = {}
    for spec in args.group:
        name, _, path = spec.partition("=")
        if not name or not path or name in groups:
            raise SystemExit(f"bad --group {spec!r}")
        groups[name] = Path(path)
    if args.reference not in groups:
        raise SystemExit(f"reference group {args.reference!r} not given")

    loaded = {name: load_group(name, path) for name, path in groups.items()}
    ref_cases = loaded[args.reference][1]

    # one row per input record: deterministic fields first, judge fields filled later
    rows: list[dict] = []
    for name, (records, cases) in loaded.items():
        if name != args.reference:
            n = check_against_reference(name, cases, ref_cases)
            log.info("hard check %-12s %3d cases: input and expected_output identical to %s",
                     name, n, args.reference)
        no_dev = 0
        for rec in records:
            if not (rec.get("dev_region") or "").strip():
                no_dev += 1          # empty developer region: outside Dataset B by definition
                continue
            key = (rec.get("id"), rec.get("provider"))
            case = cases.get(key)
            outcome = classify(rec)
            judge = case is not None and (name == args.reference or outcome in JUDGED_OUTCOMES)
            valid, valid_reason = structural(case)
            if rec.get("setting") == "agent" and valid is not None and \
                    rec.get("final_valid") is not None and valid != rec["final_valid"]:
                log.warning("%s %s/%s: (2) here=%s, harness scorer=%s", name, *key, valid,
                            rec["final_valid"])
            rows.append({"kind": "verdict", "group": name, "id": key[0], "provider": key[1],
                         "model": rec.get("model"), "valid_conflict": rec.get("valid_conflict"),
                         "outcome": outcome, "judged": judge, "accept": None,
                         "accept_score": None, "accept_reason": None,
                         "structurally_valid": valid, "valid_reason": valid_reason,
                         "_case": case if judge else None})
        if no_dev:
            log.info("group %s: %d record(s) with an empty developer region skipped", name, no_dev)

    table = Counter((r["group"], r["outcome"], r["judged"]) for r in rows)
    log.info("records by group / outcome / judged:")
    for (g, o, j), n in sorted(table.items()):
        log.info("  %-12s %-16s judged=%-5s %4d", g, o, j, n)
    to_judge = [r for r in rows if r["judged"]]
    log.info("judge calls needed: %d (judge=%s, threshold=%s)", len(to_judge),
             config.JUDGE_MODEL[1], args.threshold)
    if args.dry_run:
        return

    # output file: header + steps + verdicts (append-only so an interruption loses nothing)
    steps: list[str] | None = None
    done: set[tuple] = set()
    if args.resume:
        out_path = Path(args.resume)
        for line in out_path.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r["kind"] == "_steps":
                steps = r["evaluation_steps"]
            elif r["kind"] == "verdict" and not r.get("judge_error"):
                done.add((r["group"], r["id"], r["provider"]))
        log.info("resuming %s: %d verdicts already written, steps %s", out_path, len(done),
                 "loaded" if steps else "not yet generated")
    else:
        stamp = time.strftime("%Y%m%d_%H%M%S")
        out_path = Path(args.out) if args.out else (
            config.OUTPUT_DIR / "deepeval" / f"unified_eval_{stamp}.jsonl")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        header = {"kind": "_meta", "judge": config.JUDGE_MODEL[1], "threshold": args.threshold,
                  "deepeval": importlib_metadata.version("deepeval"), "seed": args.seed,
                  "reference": args.reference, "started": stamp,
                  "groups": {n: {"path": str(p), "sha256": sha256(p),
                                 "records": len(loaded[n][0])} for n, p in groups.items()}}
        out_path.write_text(json.dumps(header, ensure_ascii=False) + "\n", encoding="utf-8")

    judge = metrics.resolution_acceptability_metric(threshold=args.threshold,
                                                    evaluation_steps=steps)
    pending = [r for r in rows if (r["group"], r["id"], r["provider"]) not in done]
    random.Random(args.seed).shuffle(pending)
    with open(out_path, "a", encoding="utf-8") as fh:
        def write(obj: dict) -> None:
            fh.write(json.dumps(obj, ensure_ascii=False) + "\n")
            fh.flush()

        for i, r in enumerate(pending, 1):
            case = r.pop("_case")
            if case is not None:
                try:
                    score = judge.measure(case)
                    r.update(accept=bool(judge.success), accept_score=round(float(score), 3),
                             accept_reason=judge.reason)
                except Exception as e:   # transient API error: recorded, retried on --resume
                    r["judge_error"] = repr(e)
                    log.warning("[%d/%d] %s %s/%s judge error: %s", i, len(pending), r["group"],
                                r["id"], r["provider"], e)
                if steps is None and judge.evaluation_steps:
                    steps = list(judge.evaluation_steps)
                    write({"kind": "_steps", "evaluation_steps": steps})
                    log.info("evaluation steps (generated once, shared by all cases):\n  %s",
                             "\n  ".join(steps))
            write(r)
            if i % 20 == 0:
                log.info("  %d/%d", i, len(pending))
    log.info("verdicts -> %s", out_path)


if __name__ == "__main__":
    main()
