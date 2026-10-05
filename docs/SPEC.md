# ConflictAgent SPEC

This is the current stable design reference. Historical decisions and false starts are summarized
in [DEVELOPMENT_LOG.md](DEVELOPMENT_LOG.md).

## Goal

ConflictAgent measures how well modern LLMs resolve real Java merge conflicts from ConflictBench.
The project combines:

- a solver agent that generates and validates candidate resolutions without seeing ground truth;
- a GEval (DeepEval) LLM-as-judge, validated against ConflictBench's human labels on the tools' resolutions (precision 100% / recall 64.6%, n=292);
- a comparison against the five traditional ConflictBench merge tools (trivial baselines were used in an earlier milestone).

## Data

ConflictBench has 180 textual merge scenarios, published as 136 true and 44 false conflicts; this
project reclassifies one (orientdb@501dac79, true → false; see DATA.md), giving 135 / 45. There are 106 Java scenarios; 93 are
reconstructable from complete base/left/right files and are the primary solver-evaluation set.

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
resolution from `child`, use ConflictBench human labels, and invoke the ① GEval judge.

## Solver Input

The solver does not receive the whole file when the file is large. It receives a window:

- package/import/type skeleton;
- the smallest complete brace scope enclosing the target conflict block;
- elision markers for omitted code;
- exactly one target conflict block tagged with `[[RESOLVE THIS CONFLICT]]`.

Files with at most `WINDOW_FULLFILE_MAX_LINES` lines are shown whole. Windowing affects only model
context; validation and splicing always use the full reconstructed file.

## Prompt Schemes

Both schemes are kept as methodology, but they play different roles and are not pooled.

- `A`: the **primary scored scheme**. The model always produces a resolution plus self-reported
  strategy and confidence. The headline developer-match numbers come from Scheme A only.
- `B`: a **detection / robustness variant**, not part of the headline. The model first returns
  either `TRUE_CONFLICT` and punts, or `RESOLVABLE` and then resolves. Its value is measuring whether
  the model can *detect* a genuinely unresolvable conflict (see `detection` below), not the
  resolution acceptance rate. Reported separately as a capability, never mixed into the A headline.

Prompt text is in [PROMPTS.md](PROMPTS.md).

## Metrics

Primary (the two-metric suite):

- ① `developer-match` (ResolutionAcceptability, GEval): the validated LLM judge decides whether the
  candidate is an acceptable semantic match for the developer resolution. Valid for true and false
  conflicts; the true-conflict rate is the headline. Judge credibility itself: precision 100% /
  recall 64.6% (n=292) vs human labels on tool resolutions.
- ② `structural-validity` (deterministic, no LLM): no leftover markers, parses via `javalang`, no
  over-scoped duplicate declarations. Reported independently — ② does NOT gate ①.

Secondary / retained:

- `standalone-valid`: candidate judged against base/left/right without the developer answer.
  Meaningful only for false conflicts, where an objective mechanical merge can exist. Retained as a
  supplementary measure; raw data kept.
- `detection`: Scheme B only. Punt is treated as predicting a true conflict — a robustness capability,
  not part of the A headline.
- `confidence calibration`: developer-match rate by model self-reported confidence (earlier milestone,
  hand-built judge; not re-scored by the DeepEval suite).
- trivial baselines: `pick-left`, `pick-right`, `pick-longer`, `union` (earlier milestone, hand-built
  judge; not re-scored by the DeepEval suite).

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

The pipeline is complete and reimplemented on DeepEval (June–July 2026):

- data fetch and reconstruction;
- Scheme A solver prompting (scored) + Scheme B detection variant;
- windowed context;
- validate-and-retry loop (② structural gate at gen time);
- ① GEval judge validated vs human labels (P=100% / R=64.6%, n=292);
- ② structural-validity metric (≈95.8%);
- solver-line evaluation (Dataset B) with ① + ②;
- LLM versus five-tool comparison under the same ① judge (true conflicts, n=49: LLM 55–59% vs strongest tool AutoMerge 38.8%; the tools leave 20–92% unresolved).

The hand-built judge (2026-06) is superseded; see DEVELOPMENT_LOG.

Remaining optional work:

- Phase 2 trajectory eval (score ① + ② per retry round);
- report developer-match on `final_valid=True` only as a supplementary table;
- add tests around duplicate-declaration validation and prompt parsing.
