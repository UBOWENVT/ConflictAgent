"""Per-sample process metrics from Inspect logs, plus a token-cost estimate and extrapolation.

    python -m harness.analyze logs/2026-*.eval [--csv metrics.csv] [--dump transcripts/]
    python -m harness.analyze --single-shot outputs/eval/runs/eval_A_....jsonl [--csv rounds.csv]
    python -m harness.analyze logs/2026-*.eval --signals --csv signals.csv

Costs are tokens x list price (PRICES, USD per 1M tokens), computed after the fact: Inspect has
no price data for these models, so cost_limit is not used during runs (token_limit is).
Inspect's input_tokens excludes cache hits, which are billed separately at the cached rate.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
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
SINGLE_SHOT_PRICES = {"openai": PRICES["openai/gpt-5.4-2026-03-05"],
                      "gemini": PRICES["google/gemini-3.5-flash"]}
CHARS_PER_TOKEN = 4     # rough rule for English text and code
FIELDS_CHARS = 300      # REASONING / STRATEGY / CONFIDENCE fields around a resolution
RETRY_CHARS = 400       # the headings and validator error a retry adds to the prompt
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



# Process signals for the failure analysis (docs/HARNESS.md), read off the tool calls.
SEARCH = re.compile(r"\bgrep\b|\bdiff\b")
PROBE = re.compile(r"(^|[;&|]\s*|\s)(find|ls|git|stat|which|pwd|tree)\b|diff -r|cat /|/opt|/etc|env\b")
CHECKER_DIR = "/opt/harness"


def process_signals(model: str, sample: EvalSample) -> dict:
    """Yes/no signals of how one sample went about the task, to cross with its outcome."""
    calls = _tool_calls(sample)
    names = [f for f, _ in calls]
    bash = [a.get("command", "") for f, a in calls if f == "bash"]
    first = lambda t: names.index(t) if t in names else len(names)  # noqa: E731
    return {
        "model": model, "id": sample.metadata["scenario_id"],
        "searched": any(SEARCH.search(c) for c in bash),           # grep / diff inside the files
        "probed_environment": any(PROBE.search(c) for c in bash),  # find, ls, git, /opt, ...
        "checked_before_editing": first("check_java") < first("replace_text"),
        "read_checker_source": any(CHECKER_DIR in json.dumps(a) for f, a in calls
                                   if f in ("bash", "view_file")),
    }

def _clip(text: str, n: int) -> str:
    text = text.strip()
    return text if len(text) <= n else text[:n] + f" ... [{len(text) - n} more chars]"


def trajectory_text(model: str, sample: EvalSample, clip: int = 1500) -> str:
    """A readable transcript of one sample: the model's text, each tool call and its output."""
    served = sorted({e.output.model for e in sample.events
                     if e.event == "model" and getattr(e, "output", None)})
    score = (sample.scores or {}).get(SCORER)
    lines = [f"# {sample.id} | requested {model} | served {', '.join(served)}",
             f"# outcome {score.metadata['outcome'] if score else 'error'}"
             f" | limit {sample.limit.type if sample.limit else '-'}"
             f" | error {sample.error.message[:200] if sample.error else '-'}", ""]
    step = 0
    for m in sample.messages:
        if m.role == "assistant":
            step += 1
            if m.text and m.text.strip():
                lines.append(f"[{step}] assistant: {_clip(m.text, clip)}")
            for tc in m.tool_calls or []:
                args = ", ".join(f"{k}={_clip(repr(v), clip)}" for k, v in tc.arguments.items())
                lines.append(f"[{step}] -> {tc.function}({args})")
        elif m.role == "tool":
            body = f"ERROR {m.error.type}: {m.error.message}" if m.error else m.text
            lines.append(f"      <- {m.function}: {_clip(body, clip)}")
    if score is not None:
        lines += ["", f"# extracted resolution ({score.metadata['extraction']}):",
                  score.answer or "(none)"]
    return "\n".join(lines) + "\n"


def collect(log_paths: list[str], dump_dir: str | None = None, signals: bool = False) -> list[dict]:
    rows = []
    for p in log_paths:
        lg = read_eval_log(p)
        for s in lg.samples or []:
            rows.append((process_signals if signals else sample_metrics)(lg.eval.model, s))
            if dump_dir:
                d = Path(dump_dir) / lg.eval.model.replace("/", "_")
                d.mkdir(parents=True, exist_ok=True)
                (d / f"{s.id}.txt").write_text(trajectory_text(lg.eval.model, s),
                                               encoding="utf-8")
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


def single_shot_rows(run_jsonl: str) -> list[dict]:
    """Per-record rough token use of a scripts/run_eval.py run, which records no token usage.

    Each record's prompt is rebuilt with the pipeline's own code and its characters are counted. A
    retry resends the prompt plus the previous attempt (taken to be as long as the final
    resolution) and the validator error. Visible text only: thinking tokens are not recorded, so
    they are not counted. Cached-input discounts are ignored."""
    from conflictagent import solver
    from harness.dataset import build_samples
    samples = {s.id: s for s in build_samples()}
    rows = []
    for line in Path(run_jsonl).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("kind") != "llm":
            continue
        s = samples[r["id"]]
        window = solver.build_window(s.files[s.metadata["conflict_path"]], s.metadata["target_idx"])
        system, user = solver.build_prompt("A", window)
        res = len(r.get("final_resolution") or "")
        n = r.get("n_rounds") or 1
        tin = (n * (len(system) + len(user)) + (n - 1) * (res + RETRY_CHARS)) / CHARS_PER_TOKEN
        tout = n * (res + FIELDS_CHARS) / CHARS_PER_TOKEN
        p_in, _, p_out = SINGLE_SHOT_PRICES[r["provider"]]
        rows.append({"provider": r["provider"], "id": r["id"],
                     "valid_conflict": r.get("valid_conflict"),
                     "n_blocks": s.metadata["n_blocks"], "status": r.get("status"),
                     "model_calls": n, "final_valid": r.get("final_valid"),
                     "est_input_tokens": round(tin), "est_visible_output_tokens": round(tout),
                     "est_cost_usd": round((tin * p_in + tout * p_out) / 1e6, 6)})
    return rows


def single_shot_estimate(run_jsonl: str) -> str:
    """Summary of single_shot_rows() per provider."""
    lines = []
    rows = single_shot_rows(run_jsonl)
    for prov in sorted({r["provider"] for r in rows}):
        rs = [r for r in rows if r["provider"] == prov]
        calls = sum(r["model_calls"] for r in rs)
        tin = sum(r["est_input_tokens"] for r in rs)
        tout = sum(r["est_visible_output_tokens"] for r in rs)
        p_in, _, p_out = SINGLE_SHOT_PRICES[prov]
        lines.append(f"== {prov}: {len(rs)} records, {calls} model calls ({calls / len(rs):.2f} per "
                     f"record); ~{tin / 1e3:.0f}k input + ~{tout / 1e3:.0f}k visible output tokens "
                     f"-> ~${(tin * p_in + tout * p_out) / 1e6:.2f} (estimate, no thinking tokens)")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("logs", nargs="*")
    ap.add_argument("--csv", default=None)
    ap.add_argument("--dump", default=None, help="write one readable transcript per sample here")
    ap.add_argument("--single-shot", default=None, metavar="RUN_JSONL",
                    help="estimate the token cost of a scripts/run_eval.py run instead")
    ap.add_argument("--signals", action="store_true",
                    help="write the per-sample process signals (needs --csv) instead of the metrics")
    args = ap.parse_args()
    if args.single_shot:
        print(single_shot_estimate(args.single_shot))
        if args.csv:
            _write_csv(args.csv, single_shot_rows(args.single_shot))
        return
    if not args.logs:
        ap.error("give Inspect logs, or --single-shot RUN_JSONL")
    if args.signals:
        if not args.csv:
            ap.error("--signals needs --csv")
        rows = collect(args.logs, signals=True)
        for k in ("searched", "probed_environment", "checked_before_editing", "read_checker_source"):
            print(k, dict(Counter((r["model"], r[k]) for r in rows if r[k])))
        _write_csv(args.csv, rows)
        return
    rows = collect(args.logs, args.dump)
    print(summarize(rows))
    if args.csv:
        _write_csv(args.csv, rows)


def _write_csv(path: str, rows: list[dict]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"per-sample rows -> {path}")


if __name__ == "__main__":
    main()
