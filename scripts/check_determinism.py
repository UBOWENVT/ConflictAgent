"""Determinism spot-check: does temperature=0 actually make the solver reproducible?

Runs the agent loop TWICE on the first N reconstructable Java scenarios and reports whether the
two runs produce the same resolution. This isolates the solver model's decoding determinism — it
does NOT call the judge, so judge variance can't muddy the signal (unlike re-running run_eval and
comparing the summary).

Interpreting the result:
  - all SAME  -> temperature=0 is effective; runs are reproducible. Good.
  - some DIFF -> either the model ignores temperature (accepts it but fixes sampling internally),
                 or there's server-side nondeterminism. Note that even at temperature=0 LLM APIs
                 are not always bit-identical, so a rare near-miss isn't alarming; widespread DIFF
                 means temperature=0 is not buying us reproducibility.

Run:  python scripts/check_determinism.py --provider openai --limit 3 --scheme A
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from conflictagent import data, agent  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="openai")
    ap.add_argument("--scheme", default="A")
    ap.add_argument("--limit", type=int, default=3)
    args = ap.parse_args()

    usable = []
    for s in data.load_scenarios(java_only=True):
        fv = data.load_full_versions(s)
        if fv:
            usable.append((s, fv))
        if len(usable) >= args.limit:
            break

    print(f"Determinism check: {len(usable)} scenarios x2 | provider={args.provider} "
          f"scheme={args.scheme}\n")

    def _norm(t: str) -> str:
        # whitespace-normalized: judge + javalang both ignore whitespace, so a whitespace-only
        # difference is reproducible for our purposes. Compares the SEMANTIC content.
        return "\n".join(l.strip() for l in (t or "").splitlines() if l.strip())

    semantic_ok = True
    byte_ok = True
    for s, fv in usable:
        r1 = agent.resolve(args.provider, s, fv, scheme=args.scheme)
        r2 = agent.resolve(args.provider, s, fv, scheme=args.scheme)
        f1, f2 = r1.get("final_resolution"), r2.get("final_resolution")
        status_same = r1.get("status") == r2.get("status")
        byte_same = status_same and (f1 == f2)
        norm_same = status_same and (_norm(f1) == _norm(f2))
        byte_ok = byte_ok and byte_same
        semantic_ok = semantic_ok and norm_same
        tag = "SAME" if byte_same else ("WS-ONLY" if norm_same else "DIFF")
        print(f"{tag:8s} {s.id:34s} "
              f"status={r1.get('status')}/{r2.get('status')} "
              f"strat={r1.get('strategy')}/{r2.get('strategy')} "
              f"conf={r1.get('confidence')}/{r2.get('confidence')}")
        if not norm_same:
            print("  --- run 1 resolution ---\n" + (f1 or "(none)"))
            print("  --- run 2 resolution ---\n" + (f2 or "(none)"))

    if semantic_ok:
        msg = ("\n=> Semantically deterministic" +
               (" and byte-identical." if byte_ok else "; only whitespace/formatting varied.") +
               " Eval scores are reproducible (judge + javalang ignore whitespace).")
    else:
        msg = ("\n=> NON-deterministic in CONTENT: temperature=0 isn't fixing the actual code "
               "(model ignores it or server nondeterminism). Reproducibility is nice-to-have, "
               "not blocking.")
    print(msg)


if __name__ == "__main__":
    main()
