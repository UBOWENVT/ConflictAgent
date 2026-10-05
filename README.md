# ConflictAgent

ConflictAgent evaluates modern LLMs on real Java merge conflicts from
[ConflictBench](https://github.com/UBOWENVT/ConflictBench). It wraps solver models in a
generate-validate-retry loop, then scores the final resolutions with a separately calibrated
LLM-as-judge.

It is an evaluation harness, not a new benchmark: ConflictBench supplies the data, developer
resolutions, human labels, and the five traditional merge-tool baselines; ConflictAgent supplies the
LLM agent and the evaluation pipeline.

## Current Status

Current as of the 2026-07 DeepEval + pipeline-hardening iteration.

- Reconstructable Java scenarios: 93 of 106 Java ConflictBench scenarios.
- Solvers: OpenAI `gpt-5.4-2026-03-05` and Gemini `gemini-3.5-flash` (forced-resolution mode).
- Judge: Anthropic `claude-sonnet-4-6`, reimplemented as a DeepEval GEval metric. It is calibrated
  against ConflictBench's human labels on the five tools' resolutions, then used to score the LLM
  outputs (a different vendor from both solvers).
- Judge calibration (Dataset A, n=292): **precision 100%** (zero false accepts), recall 64.6%.
- Solver developer-match on true conflicts: **≈55%** (conservative floor: the lower of the two
  providers; pooled 58.3%). LLM vs the five traditional tools (coverage-fair, n=49 true): LLM 55–59%
  vs strongest tool AutoMerge 38.8%. The edge is coverage: the tools leave 20–92% of these conflicts
  unresolved, while the LLM under forced resolution attempts every one.
- Structural validity on true conflicts: 95.8% (deterministic check, no LLM).
- The agent also supports a detection mode (Scheme B: the model may declare a true conflict and
  decline to resolve). It was run in an earlier milestone and is not re-scored by the current GEval
  judge.

The judge and solver figures above can be recomputed from the frozen results in `results/` with no
API key: `python scripts/verify_numbers.py`. The tool comparison additionally needs the public
ConflictBench labels; see [docs/REPRODUCE.md](docs/REPRODUCE.md).

## Architecture

Two layers are kept strictly separate.

**Agent loop: no ground truth**

1. Reconstruct a diff3 conflict file from base/left/right using `git merge-file --diff3`.
2. Select the target conflict block using ConflictBench's annotated merged snippet.
3. Show the solver a window: file skeleton plus the smallest brace scope around the target block.
4. Ask the solver to produce a replacement for only the tagged conflict region.
5. Splice the candidate back into the full reconstructed file.
6. Validate with inference-time signals only: conflict markers, Java syntax via `javalang`, and
   duplicate declaration checks for over-scoped output.
7. Retry up to `MAX_RETRIES` when validation fails.

**Evaluation: uses ground truth outside the loop**

The judge compares candidate resolutions against the developer's actual resolution extracted from
the `child` file. This is offline-only; the agent loop never sees the developer answer.

## Why There Is No Single-Shot Baseline

An earlier design compared the retry loop against a single-shot round-0 baseline. That was dropped
after full runs showed modern solver models usually emit syntactically valid answers on the first
try, so retry-loop delta was not the main signal.

The evaluation instead compares the LLM with the five traditional tools under the same judge.
Trivial baselines (`pick-left`, `pick-right`, `pick-longer`, `union`) were scored in the earlier
milestone runs with the hand-built judge; they are not re-scored by the current DeepEval suite, and
`docs/CASE_STUDIES.md` uses them to illustrate individual cases.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python scripts/fetch_data.py
```

Fill `.env` with provider keys before running solver or judge scripts.

## Main Commands

Verify the reported numbers from the frozen results (no API key, no LLM calls):

```bash
python scripts/verify_numbers.py
```

Smoke-test provider access:

```bash
python scripts/smoke_test_llm.py
```

Run the solver agent and score it (Scheme A = forced resolution, the scored line):

```bash
python scripts/run_eval.py --scheme A --providers openai gemini --no-judge   # solver only -> outputs/eval/runs/
python evaluation/build_complete_set.py                                      # one record per scenario x provider
python -m evaluation.run_solver_eval                                         # ① GEval developer-match + ② structural validity
```

`--no-judge` skips the script's legacy built-in judge; scoring is done by the DeepEval suite. To
re-run specific scenarios, add `--only-ids Terasology@abcd1234`. Scheme B (detection mode: the model
may declare a true conflict and decline to resolve) runs with `--scheme B` but is not part of the
scored results.

Validate the judge against human labels (Dataset A meta-evaluation, n=292):

```bash
python -m evaluation.run_suite
```

Compare the LLM with the five ConflictBench tools under the same judge (no LLM calls; needs the
ConflictBench labels from `scripts/fetch_data.py`):

```bash
python scripts/compare_tools_geval.py --llm results/solver_eval_20260627_095221.jsonl \
    --tool results/meta_evaluation_20260727_062930.jsonl
```

## Repository Layout

```text
conflictagent/      core package: data, conflict reconstruction, solver, agent loop, validation
evaluation/         DeepEval suite: judge meta-evaluation and solver scoring
scripts/            data fetch, solver runs, comparisons, diagnostics
results/            frozen judge and solver results behind the reported numbers
docs/               project documentation
data/               local ConflictBench data, gitignored
outputs/            local experiment outputs, gitignored
```

Start with [docs/SPEC.md](docs/SPEC.md), then [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and
[docs/RESULTS.md](docs/RESULTS.md).

## Documentation

- [docs/SPEC.md](docs/SPEC.md): stable current design.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): code and data-flow map.
- [docs/RESULTS.md](docs/RESULTS.md): grounded results and interpretation.
- [docs/CASE_STUDIES.md](docs/CASE_STUDIES.md): representative examples for explaining metrics.
- [docs/DATA.md](docs/DATA.md): ConflictBench schema, reconstruction, and gotchas.
- [docs/PROMPTS.md](docs/PROMPTS.md): exact solver prompts.
- [docs/REPRODUCE.md](docs/REPRODUCE.md): how to recompute the reported numbers.
- [docs/DEVELOPMENT_LOG.md](docs/DEVELOPMENT_LOG.md): compressed development history.

## Credits

Built on ConflictBench: Shen and Meng, *Journal of Systems and Software*, 214, 2024.

## License

MIT, see [LICENSE](LICENSE). ConflictBench data is not redistributed here; `scripts/fetch_data.py`
downloads it from the [ConflictBench repository](https://github.com/UBOWENVT/ConflictBench).
