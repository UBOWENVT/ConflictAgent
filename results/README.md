# Frozen results

The two files here are the per-case outputs behind the judge and solver numbers reported in the
README and `docs/RESULTS.md`. They are committed so the numbers can be checked without API keys or LLM calls:

```bash
python scripts/verify_numbers.py
```

| File | Rows | Each row |
| --- | --- | --- |
| `meta_evaluation_20260727_062930.jsonl` | 292 | one ① GEval judge verdict on a ConflictBench tool resolution, next to its human label (judge calibration) |
| `solver_eval_20260627_095221.jsonl` | 132 | one (scenario × provider) LLM resolution with its ① developer-match verdict and ② structural-validity result |

They contain verdicts, scores and the judge's short reasons; they do not contain the conflict files
or the resolutions themselves. Reruns write new timestamped files under `outputs/deepeval/`
(gitignored); these frozen copies stay as they are. See `docs/REPRODUCE.md` for the field
definitions and how each number is derived.
