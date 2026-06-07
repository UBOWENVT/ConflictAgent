"""Run the validate-and-repair agent loop over scenarios; dump per-round records.

Only scenarios whose full files were fetched (data.load_full_versions) are runnable.
Records are written incrementally as JSONL (crash-safe), and a summary prints the headline:
baseline (round 0, loop off) vs after-loop syntax-valid counts per provider.

Run:  python scripts/run_agent.py                       # default: 5 scenarios, both solvers
      python scripts/run_agent.py --limit 0             # all reconstructable scenarios
      python scripts/run_agent.py --providers openai    # one solver
      python scripts/run_agent.py --java-only --limit 20
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from conflictagent import agent, config, data  # noqa: E402


def _round0_valid(rec: dict) -> bool:
    return rec.get("status") == "ok" and rec["rounds"][0]["valid"]


def _final_valid(rec: dict) -> bool:
    return rec.get("status") == "ok" and bool(rec.get("final_valid"))


def _print_line(rec: dict) -> None:
    if rec.get("status") == "ok":
        r0 = "✓" if rec["rounds"][0]["valid"] else "✗"
        rf = "✓" if rec["final_valid"] else "✗"
        print(f"  {rec['id']:32s} {rec['provider']:8s} round0={r0} final={rf} "
              f"(rounds={rec['n_rounds']})")
    else:
        print(f"  {rec['id']:32s} {rec.get('provider',''):8s} [{rec.get('status')}]")


def _summary(records: list[dict], providers: list[str]) -> None:
    print("\n=== summary (syntax-valid: baseline round0 -> after loop) ===")
    for p in providers:
        recs = [r for r in records if r.get("provider") == p]
        ok = [r for r in recs if r.get("status") == "ok"]
        b = sum(_round0_valid(r) for r in ok)
        f = sum(_final_valid(r) for r in ok)
        skipped = len(recs) - len(ok)
        n = len(ok)
        print(f"  {p:8s}  ok={n:3d}  baseline {b}/{n}  ->  after-loop {f}/{n}"
              + (f"  (+{f - b})" if n else "") + f"   [skipped {skipped}]")


def run(providers: list[str], runnable: list, out_path: Path) -> list[dict]:
    records: list[dict] = []
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        for s, fv in runnable:
            for provider in providers:
                try:
                    rec = agent.resolve(provider, s, fv)
                except Exception as e:  # network / API / parse — keep going
                    rec = {"id": s.id, "provider": provider, "status": "error", "error": repr(e)}
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fh.flush()
                records.append(rec)
                _print_line(rec)
    return records


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--providers", default=",".join(config.SOLVER_MODELS),
                    help="comma-separated solver providers")
    ap.add_argument("--limit", type=int, default=5,
                    help="number of scenarios (0 = all reconstructable)")
    ap.add_argument("--java-only", action="store_true")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    providers = [p.strip() for p in args.providers.split(",") if p.strip()]
    scenarios = data.load_scenarios(java_only=args.java_only)
    runnable = [(s, fv) for s in scenarios if (fv := data.load_full_versions(s)) is not None]
    if args.limit:
        runnable = runnable[: args.limit]

    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_path = Path(args.out) if args.out else config.OUTPUT_DIR / "agent_runs" / f"run_{stamp}.jsonl"

    print(f"Running {len(runnable)} scenarios x {providers} (retries<= {config.MAX_RETRIES})")
    records = run(providers, runnable, out_path)
    _summary(records, providers)
    print(f"\nRecords -> {out_path}")


if __name__ == "__main__":
    main()
