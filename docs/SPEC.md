# ConflictAgent SPEC

This is the current stable design reference. Historical decisions and false starts are summarized
in [DEVELOPMENT_LOG.md](DEVELOPMENT_LOG.md).

## Goal

ConflictAgent measures how well modern LLMs resolve real Java merge conflicts from ConflictBench.
The project combines:

- a solver agent that generates and validates candidate resolutions without seeing ground truth;
- an offline LLM-as-judge calibrated against ConflictBench human labels;
- comparisons against trivial baselines and the five traditional ConflictBench merge tools.

## Data

ConflictBench has 180 textual merge scenarios: 136 true conflicts and 44 false conflicts. There are
106 Java scenarios; 93 are reconstructable from complete base/left/right files and are the primary
evaluation set.

Each scenario has:

- `base`: common ancestor;
- `left` and `right`: branch versions;
- `child`: developer resolution, used only by evaluation;
- tool outputs for FSTMerge, JDime, IntelliMerge, AutoMerge, and KDiff3 when available;
- xlsx labels, snippets, strategy fields, and human desirability judgments.

## Two-Layer Rule

The project depends on a strict separation.

**Agent loop: no ground truth**

The loop may use only inference-time signals:

- conflict marker checks;
- Java syntax parsing through `javalang`;
- duplicate declaration checks that catch over-scoped output;
- retry feedback from those validators.

It must not see the developer resolution or judge verdicts.

**Evaluation layer: ground truth allowed**

Evaluation runs after the agent finishes. It may compare the candidate with the developer's actual
resolution from `child`, use ConflictBench human labels, and invoke the judge.

## Solver Input

The solver does not receive the whole file when the file is large. It receives a window:

- package/import/type skeleton;
- the smallest complete brace scope enclosing the target conflict block;
- elision markers for omitted code;
- exactly one target conflict block tagged with `[[RESOLVE THIS CONFLICT]]`.

Files with at most `WINDOW_FULLFILE_MAX_LINES` lines are shown whole. Windowing affects only model
context; validation and splicing always use the full reconstructed file.

## Prompt Schemes

Both schemes are run because they measure different behavior.

- `A`: primary scheme. The model always produces a resolution plus self-reported strategy and
  confidence.
- `B`: ablation scheme. The model first returns either `TRUE_CONFLICT` and punts, or `RESOLVABLE`
  and then produces a resolution.

Prompt text is in [PROMPTS.md](PROMPTS.md).

## Metrics

Primary metric:

- `developer-match`: the calibrated judge decides whether the candidate is an acceptable semantic
  match for the developer resolution. This is valid for true and false conflicts.

Secondary metrics:

- `standalone-valid`: candidate is judged against base/left/right without the developer answer.
  This is meaningful only for false conflicts, where an objective mechanical merge can exist.
- `detection`: only for scheme B. Punt is treated as predicting a true conflict.
- `confidence calibration`: developer-match rate by model self-reported confidence.
- trivial baselines: `pick-left`, `pick-right`, `pick-longer`, `union`.

Deprecated metrics:

- token-level F1;
- retry-round syntax-valid curve as the headline;
- single-shot round-0 baseline as the primary baseline.

These were dropped because full runs showed first-round solver output is usually already
syntactically valid; the key question became semantic quality versus baselines and tools.

## Models

- Solvers: `openai:gpt-5.4-2026-03-05`, `gemini:gemini-3.5-flash`.
- Judge: `anthropic:claude-sonnet-4-6`.
- Solver and judge are intentionally different vendors to reduce self-preference.
- Temperature is `0` for reproducible evaluation.

## Current State

The pipeline is complete:

- data fetch and reconstruction;
- A/B solver prompting;
- windowed context;
- validate-and-retry loop;
- developer-match judge calibration;
- standalone judge calibration sample;
- full A/B evaluations;
- LLM versus five-tool comparison.

Remaining optional work:

- further tighten standalone-valid judging on false conflicts;
- report developer-match on `final_valid=True` only as a supplementary table;
- add tests around duplicate-declaration validation and prompt parsing.
