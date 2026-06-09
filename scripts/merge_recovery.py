"""Fold transient-failure recovery runs back into the original A/B eval files.

Some gemini scenarios errored during the initial full runs with transient 503 "high demand"
ServerErrors. They were re-run individually via `run_eval.py --only-ids ...`. Since temperature=0
and scenarios are independent, a recovered scenario's result is equivalent to what the full run
would have produced; a 503 is an infrastructure failure, not a result. This script replaces each
gemini error record in the original file with its recovered (non-error) record, by scenario id,
writing eval_<scheme>_complete.jsonl. openai records and trivial baselines are left untouched.

It prints the merged gemini metrics plus an openai cross-check — openai is unchanged by the merge,
so its numbers must equal the original run's summary; that match validates the metric definitions.

Run:  python scripts/merge_recovery.py
"""
from __future__ import annotations

import json
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent.parent / "outputs" / "eval"

# original full run  ->  recovery runs that hold the re-run (non-error) records
SOURCES = {
    "A": ("eval_A_20260608_211559.jsonl",
          ["eval_A_20260609_091453.jsonl", "eval_A_20260609_101912.jsonl"]),
    "B": ("eval_B_20260609_001236.jsonl",
          ["eval_B_20260609_103639.jsonl", "eval_B_20260609_144417.jsonl"]),
}


def _load(name: str) -> list[dict]:
    with open(EVAL_DIR / name, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _is_gemini_llm(r: dict) -> bool:
    return r.get("kind") == "llm" and r.get("provider") == "gemini"


def merge(original: str, recoveries: list[str]) -> tuple[list[dict], int, int]:
    recovered: dict[str, dict] = {}
    for name in recoveries:
        for r in _load(name):
            if _is_gemini_llm(r) and "error" not in r:
                recovered[r["id"]] = r          # last recovery wins (all are temp=0 equivalent)

    out, replaced, still_error = [], 0, 0
    for r in _load(original):
        if _is_gemini_llm(r) and "error" in r:
            if r["id"] in recovered:
                out.append(recovered[r["id"]]); replaced += 1
            else:
                out.append(r); still_error += 1   # never recovered — left as error
        else:
            out.append(r)
    return out, replaced, still_error


def _rate(sub: list[dict], key: str) -> str:
    if not sub:
        return "0/0"
    a = sum(1 for r in sub if r[key])
    return f"{a}/{len(sub)} = {100 * a / len(sub):.1f}%"


def metrics(rows: list[dict], provider: str) -> str:
    g = [r for r in rows if r.get("kind") == "llm" and r.get("provider") == provider]
    errors = sum(1 for r in g if "error" in r)
    res = [r for r in g if r.get("status") == "resolved"]
    dev = [r for r in res if r.get("dev_match") is not None]
    dev_t = [r for r in dev if r["valid_conflict"]]
    dev_f = [r for r in dev if not r["valid_conflict"]]
    std = [r for r in res if r.get("standalone") is not None]
    std_t = [r for r in std if r["valid_conflict"]]
    std_f = [r for r in std if not r["valid_conflict"]]
    return (f"    errors={errors}  resolved={len(res)}\n"
            f"    dev-match      {_rate(dev, 'dev_match')}   "
            f"(true {_rate(dev_t, 'dev_match')} | false {_rate(dev_f, 'dev_match')})\n"
            f"    standalone(F)  {_rate(std_f, 'standalone')}   "
            f"(true-ref {_rate(std_t, 'standalone')})")


def main() -> None:
    for scheme, (original, recoveries) in SOURCES.items():
        merged, replaced, still_error = merge(original, recoveries)
        out_path = EVAL_DIR / f"eval_{scheme}_complete.jsonl"
        with open(out_path, "w", encoding="utf-8") as f:
            for r in merged:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"===== scheme {scheme}: replaced {replaced} gemini error rows, "
              f"still-error {still_error} =====")
        print("  GEMINI (merged, final):")
        print(metrics(merged, "gemini"))
        print("  OPENAI cross-check (unchanged; must match the original run summary):")
        print(metrics(merged, "openai"))
        print(f"  -> wrote {out_path}\n")


if __name__ == "__main__":
    main()
