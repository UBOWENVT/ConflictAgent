# Recomputing the metrics from the on-disk JSONL

None of the headline numbers are "run-once-and-gone" — they are simple aggregations of **two per-case
JSONL files** on disk. To reproduce them, just count over those two files; **no LLM calls needed**.

| Metric | File on disk | Rows | What each row is |
| --- | --- | --- | --- |
| ① judge line (validate the judge) 100% / 64.6% | `outputs/deepeval/meta_evaluation_20260727_062930.jsonl` | 292 | one judge verdict vs its human label |
| ①+② solver line (measure the LLM) ≈55% / 95.8% | `outputs/deepeval/solver_eval_20260627_095221.jsonl` | 132 | one (scenario × provider) with ① accept + ② structurally_valid |

> Filenames are timestamped; a rerun writes a new one, so take the latest `meta_evaluation_*` /
> `solver_eval_*` in `outputs/deepeval/`. The older `metaval_2026062*` (303/310 rows) are the
> superseded early cut, and `judge_calibration/calib_*` (563 rows) is the hand-built-judge era — both
> historical.

---

## 1. Judge line: precision 100% / recall 64.6% (n=292)

Each row of `meta_evaluation_*.jsonl`: `{project, commit, tool, source, human(bool), judge(bool), score, reason}`.
`human` = the human 0/1 label, `judge` = the GEval verdict. Confusion matrix:

```python
import json
rows = [json.loads(l) for l in open("outputs/deepeval/meta_evaluation_20260727_062930.jsonl") if l.strip()]
TP = sum(r["judge"] and r["human"] for r in rows)          # 117
FP = sum(r["judge"] and not r["human"] for r in rows)      # 0
TN = sum(not r["judge"] and not r["human"] for r in rows)  # 111
FN = sum(not r["judge"] and r["human"] for r in rows)      # 64
precision = TP/(TP+FP)          # 100.0%
recall    = TP/(TP+FN)          # 64.6%
accuracy  = (TP+TN)/len(rows)   # 78.1%
```

FP=0 → precision 100% (when the judge says "acceptable" it is never wrong); recall 64.6% → conservative,
it misses some resolutions that are in fact acceptable.

## 2. Solver line: true-conflict dev-match ≈55% floor, structural validity 95.8%

Each row of `solver_eval_*.jsonl`: `{id, provider, valid_conflict(bool), accept(bool, ①), accept_score, structurally_valid(bool, ②), accept_reason, valid_reason}`.

```python
s = [json.loads(l) for l in open("outputs/deepeval/solver_eval_20260627_095221.jsonl") if l.strip()]
true = [r for r in s if r["valid_conflict"]]               # 96 rows = 49 true scenarios × 2 providers (gemini −2)
# ① dev-match, stratified by provider:
for p in ("openai", "gemini"):
    t = [r for r in true if r["provider"] == p]
    print(p, sum(r["accept"] for r in t), "/", len(t))     # openai 27/49=55.1% · gemini 29/47=61.7%
# Headline = conservative floor = lower of the two = 55.1% (pooled is 56/96=58.3%, which we do NOT report)
# ② structural validity:
print(sum(r["structurally_valid"] for r in true), "/", len(true))   # 92/96 = 95.8%
```

Comparison against the 5 tools (AutoMerge 36.7%, etc.) comes from `scripts/compare_tools_geval.py`,
which judges each tool's resolution (from the xlsx) with **the same ① judge**, same convention.

---

## 3. Where these two JSONL come from (one level up)

If you want to re-run the judging/validation itself (which does call an LLM), rather than just
aggregate already-judged results:

```
① judge line:
  data/ConflictBench.xlsx
    → conflictagent/data.load_manual_labels()             627 labeled pairs
    → evaluation/dataset.build_metaevaluation_testcases()  drop punt/file-level/empty → 292
    → evaluation/run_suite.py  (runs ① GEval, writes meta_evaluation_*.jsonl + prints the matrix)

②+① solver line:
  data/scenarios/  → conflictagent/data.load_scenarios(java_only)  93 reconstructable
    → scripts/run_agent.py  (solver.py generate + agent.py generate-validate-retry loop,
                             writes outputs/eval/eval_A_complete.jsonl)
    → evaluation/build_complete_set.py  (assemble/dedup the complete set)
    → evaluation/dataset.build_solver_testcases()  (rebuild inputs, locate dev region → 67 scenarios → 132 records)
    → evaluation/run_solver_eval.py  (runs ①+②, writes solver_eval_*.jsonl)
```

- `outputs/eval/eval_A_complete.jsonl` (first line is a `kind=_meta` header; the rest are each
  scenario's resolution per provider) = the solver line's **pre-judging** raw material.
- The 900→292 per-point provenance for the judge line is in
  `scripts/diagnostics/judge_funnel_provenance.py` and `docs/judge_funnel_900.xlsx`.

**In one line:** want just the numbers → aggregate the two JSONL in §1–2; want to re-run the judging
too → start from `eval_A_complete.jsonl` / the xlsx and follow the script chain in §3. The
authoritative results table is `docs/RESULTS.md`.
