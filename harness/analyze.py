"""Per-sample process metrics from Inspect logs, plus a token-cost estimate and extrapolation.

    python -m harness.analyze logs/2026-*.eval [--csv outputs/stage3/trial_metrics.csv]

Costs are tokens x list price (PRICES, USD per 1M tokens), computed after the fact: Inspect has
no price data for these models, so cost_limit is not used during runs (token_limit is).
Inspect's input_tokens excludes cache hits, which are billed separately at the cached rate.
"""
from __future__ import annotations

import argparse
import csv
import statistics
import sys
from collections import Counter
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from inspect_ai.log import EvalSample, read_eval_log  # noqa: E402

# (input, cached input, output) USD per 1M tokens, checked 2026-10-09:
#   gpt-5.4: developers.openai.com/api/docs/pricing, standard tier, prompts <= 272K tokens.
#   gemini: ai.google.dev/gemini-api/docs/pricing lists 3.6 Flash (rates through 2026-12-31);
#   ai.google.dev/gemini-api/docs/deprecations says gemini-3.5-flash requests are routed to
#   gemini-3.6-flash.
PRICES = {
    "openai/gpt-5.4-2026-03-05": (2.50, 0.25, 15.00),
    "google/gemini-3.5-flash": (0.75, 0.075, 3.75),
    "google/gemini-3.6-flash": (0.75, 0.075, 3.75),
}
SCORER = "conflict_file_scorer"
TRUNCATION_NOTE = "was too long to be displayed"
N_SCENARIOS = 67


def _tool_calls(sample: EvalSample) -> list[tuple[str, dict]]:
    return [(tc.function, tc.arguments) for m in sample.messages if m.role == "assistant"
            for tc in (m.tool_calls or [])]


def sample_metrics(model: str, sample: EvalSample) -> dict:
    calls = _tool_calls(sample)
    names = [f for f, _ in calls]
    tool_msgs = [m for m in sample.messages if m.role == "tool"]
    checks = [m for m in tool_msgs if m.function == "check_java"]
    submit_at = names.index("submit") if "submit" in names else None
    before_submit = names[:submit_at] if submit_at is not None else names
    check_results = [m.text.startswith("PASS") for m in checks]
    usage = sample.model_usage.get(model)
    inp = usage.input_tokens if usage else 0
    cached = (usage.input_tokens_cache_read or 0) if usage else 0
    out = usage.output_tokens if usage else 0
    p_in, p_cached, p_out = PRICES.get(model, (float("nan"),) * 3)
    score = (sample.scores or {}).get(SCORER)
    meta = sample.metadata
    return {
        "model": model, "id": meta["scenario_id"], "valid_conflict": meta["valid_conflict"],
        "n_blocks": meta["n_blocks"],
        "file_lines": (meta["prefix"] + meta["suffix"]).count("\n"),
        "outcome": "error" if sample.error or score is None else score.metadata["outcome"],
        "extraction": score.metadata["extraction"] if score else None,
        "structurally_valid": score.metadata["structurally_valid"] if score else None,
        "submitted": "submit" in names,
        "limit": sample.limit.type if sample.limit else None,
        "error": (sample.error.message[:120] if sample.error else None),
        "model_calls": sum(1 for m in sample.messages if m.role == "assistant"),
        "tool_calls": len(calls) - names.count("submit"),
        **{f"n_{t}": names.count(t) for t in ("bash", "view_file", "replace_text", "check_java")},
        "tool_errors": sum(1 for m in tool_msgs if m.error is not None),
        "tool_parse_errors": sum(1 for m in tool_msgs
                                 if m.error is not None and m.error.type == "parsing"),
        "truncated_outputs": sum(1 for m in tool_msgs if TRUNCATION_NOTE in m.text),
        "checked_before_submit": "check_java" in before_submit,
        "last_check_passed": check_results[-1] if check_results else None,
        "fixed_after_failed_check": (False in check_results
                                     and check_results[-1] is True),
        "input_tokens": inp, "cached_tokens": cached, "output_tokens": out,
        "reasoning_tokens": (usage.reasoning_tokens or 0) if usage else 0,
        "cost_usd": (inp * p_in + cached * p_cached + out * p_out) / 1e6,
        "total_time_s": round(sample.total_time or 0, 1),
        "working_time_s": round(sample.working_time or 0, 1),
    }


def collect(log_paths: list[str]) -> list[dict]:
    rows = []
    for p in log_paths:
        lg = read_eval_log(p)
        for s in lg.samples or []:
            rows.append(sample_metrics(lg.eval.model, s))
    return rows


def summarize(rows: list[dict]) -> str:
    lines = []
    for model in sorted({r["model"] for r in rows}):
        rs = [r for r in rows if r["model"] == model]
        costs = [r["cost_usd"] for r in rs]
        tot = lambda k: sum(r[k] for r in rs)  # noqa: E731
        lines += [
            f"== {model}: {len(rs)} samples",
            f"  outcomes: {dict(Counter(r['outcome'] for r in rs))}",
            f"  limits hit: {dict(Counter(r['limit'] for r in rs if r['limit']))}  "
            f"errors: {sum(1 for r in rs if r['error'])}",
            f"  model calls / sample: mean {statistics.mean(r['model_calls'] for r in rs):.1f}, "
            f"max {max(r['model_calls'] for r in rs)}",
            f"  tool calls: bash {tot('n_bash')}, view_file {tot('n_view_file')}, "
            f"replace_text {tot('n_replace_text')}, check_java {tot('n_check_java')}; "
            f"tool errors {tot('tool_errors')} (parsing {tot('tool_parse_errors')}), "
            f"truncated outputs {tot('truncated_outputs')}",
            f"  checked before submit: {sum(r['checked_before_submit'] for r in rs)}/{len(rs)}",
            f"  tokens: input {tot('input_tokens'):,}, cached {tot('cached_tokens'):,}, "
            f"output {tot('output_tokens'):,} (reasoning {tot('reasoning_tokens'):,})",
            f"  cost: total ${sum(costs):.2f}, per sample mean ${statistics.mean(costs):.3f}, "
            f"median ${statistics.median(costs):.3f}, max ${max(costs):.3f}",
            f"  extrapolated to {N_SCENARIOS} scenarios (mean x {N_SCENARIOS}): "
            f"${statistics.mean(costs) * N_SCENARIOS:.2f}",
        ]
    total = sum(statistics.mean([r["cost_usd"] for r in rows if r["model"] == m]) * N_SCENARIOS
                for m in {r["model"] for r in rows})
    lines.append(f"== full agent run, all models (mean-based extrapolation): ${total:.2f}")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("logs", nargs="+")
    ap.add_argument("--csv", default=None)
    args = ap.parse_args()
    rows = collect(args.logs)
    print(summarize(rows))
    if args.csv:
        Path(args.csv).parent.mkdir(parents=True, exist_ok=True)
        with open(args.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print(f"per-sample rows -> {args.csv}")


if __name__ == "__main__":
    main()
