# ConflictAgent

ConflictAgent evaluates modern LLMs on real Java merge conflicts from
[ConflictBench](https://github.com/UBOWENVT/ConflictBench). It wraps solver models in a
generate-validate-retry loop, then scores the final resolutions with a separately calibrated
LLM-as-judge.

The project is built as an engineering artifact for resume/interview discussion, not as a new
research benchmark. ConflictBench supplies the data, developer resolutions, human labels, and the
five traditional merge-tool baselines; ConflictAgent supplies the LLM agent and evaluation harness.

## Current Status

Current as of the 2026-07 DeepEval + pipeline-hardening iteration.

- Reconstructable Java scenarios: 93 of 106 Java ConflictBench scenarios.
- Solvers: OpenAI `gpt-5.4-2026-03-05` and Gemini `gemini-3.5-flash` (forced-resolution mode).
- Judge: Anthropic `claude-sonnet-4-6`, reimplemented as a DeepEval GEval metric, calibrated
  against ConflictBench human labels.
- Judge calibration (Dataset A, n=292): **precision 100%** (zero false accepts), recall 64.6%.
- Solver developer-match on true conflicts: **≈55%** (conservative floor across providers; pooled
  58.3%). LLM vs the five traditional tools (coverage-fair, n=49 true): LLM 55–59% vs strongest tool
  AutoMerge 36.7% — the edge is coverage (tools abstain heavily; the LLM under forced resolution
  does not).
- Structural validity on true conflicts: 95.8%.
- The agent also supports a detection mode (predict "true conflict" and abstain), validated in the
  earlier milestone; it is not part of the current GEval-scored headline.

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

The current evaluation instead compares against stronger, more interpretable trivial baselines:
`pick-left`, `pick-right`, `pick-longer`, and `union`. These answer the harder question: does the
LLM beat simple merge heuristics and the five traditional tools under the same desirability metric?

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

Smoke-test provider access:

```bash
python scripts/smoke_test_llm.py
```

Run evaluation:

```bash
python scripts/run_eval.py --scheme A --providers openai gemini   # Scheme A = forced resolution (primary, current)
python scripts/run_eval.py --scheme B --providers openai gemini --no-baselines   # Scheme B = detection mode (may punt); supported, not in current headline
```

Recover specific failed scenarios:

```bash
python scripts/run_eval.py --scheme A --providers gemini --only-ids Terasology@abcd1234
```

Compare the LLM with the five ConflictBench tools (coverage-fair, scored by the same GEval judge):

```bash
python scripts/compare_tools_geval.py
```

Score solver resolutions with the DeepEval suite (① GEval developer-match + ② structural validity):

```bash
python -m evaluation.run_solver_eval
```

Validate the judge against human labels (Dataset A meta-evaluation, n=292):

```bash
python -m evaluation.run_suite
```

## Repository Layout

```text
conflictagent/      core package
scripts/            data, evaluation, calibration, and analysis entry points
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
- [docs/HANDOFF.md](docs/HANDOFF.md): current handoff notes.
- [docs/DEVELOPMENT_LOG.md](docs/DEVELOPMENT_LOG.md): compressed development history.

## Credits

Built on ConflictBench: Shen and Meng, *Journal of Systems and Software*, 214, 2024.
