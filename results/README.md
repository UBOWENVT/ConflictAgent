# Frozen results

The files here are the per-case outputs behind the numbers reported in the README,
`docs/RESULTS.md` and `docs/HARNESS.md`. They are committed so the numbers can be checked without
API keys or LLM calls:

```bash
python scripts/verify_numbers.py
```

| File | Rows | Each row |
| --- | --- | --- |
| `meta_evaluation_20260727_062930.jsonl` | 292 | one ① GEval judge verdict on a ConflictBench tool resolution, next to its human label (judge calibration) |
| `solver_eval_20260627_095221.jsonl` | 132 | one (scenario × provider) LLM resolution with its ① developer-match verdict and ② structural-validity result |
| `stage3_unified_eval_20261010_163404.jsonl` | 402 + 2 | one (group × scenario × provider) verdict of the stage-3 unified scoring: groups `agent`, `single_shot` (same-day rerun) and `june`; outcome, ① verdict, score and reason, ② result. Header rows: run metadata and the judge's evaluation steps |
| `stage3_agent_metrics_20261010.csv` | 134 | one agent sample: outcome, tool calls, check_java use, limits, tokens, cost, time (`harness/analyze.py`) |
| `stage3_single_shot_20261010.csv` | 134 | one single-shot rerun record: model calls (attempts) and the token estimate (`harness/analyze.py --single-shot`) |

They contain verdicts, scores and the judge's short reasons; they do not contain the conflict files
or the resolutions themselves. Reruns write new timestamped files under `outputs/deepeval/`
(gitignored); these frozen copies stay as they are. See `docs/REPRODUCE.md` for the field
definitions and how each number is derived.
