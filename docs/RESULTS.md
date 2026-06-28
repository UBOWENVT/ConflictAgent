# Results

This file records grounded results across two layers. The **judge layer** (calibration +
meta-validation + standalone) and the **current solver layer** ("DeepEval Solver Results") are
current. The hand-built-judge solver tables from the 2026-06-09 milestone are retained as
**historical / superseded** (clearly banner-marked) for traceability. Developer-match rates are
stratified by conflict type; current solver numbers come from the DeepEval suite
(`evaluation/run_solver_eval.py`, `scripts/compare_tools_geval.py`), historical ones from
`scripts/compare_tools.py`.

## Judge Calibration

The developer-match judge (claude-sonnet-4-6) was calibrated against ConflictBench's
human desirability labels for tool outputs.

- Total labeled tool pairs: 627 -> 310 desirability judgments + 253 detection
  (punt) events + 64 empty/skipped (mostly FSTMerge deletion-style resolutions).
- Developer-match, n=310: accuracy 70.6%, precision 92.9%, recall 55.6%
  (TP104 FP8 TN115 FN83).
- By conflict type: true conflicts (196) precision 90.6%, recall 67.0%; false
  conflicts (114) precision 100%, recall 37.5%.

Interpretation: the judge is high precision and conservative. An `ACCEPTABLE`
verdict is trustworthy (it almost never accepts a bad resolution); the modest
recall means it under-credits acceptable alternatives, so every developer-match
rate below is a conservative lower bound.

## Judge Meta-Validation (DeepEval re-implementation, Phase 1)

The developer-match judge above was re-implemented as a DeepEval `GEval` LLM-as-judge
metric (`evaluation/metrics.py`, `ResolutionAcceptability`) and re-validated against the
same ConflictBench human desirability labels (`evaluation/run_suite.py`). This is the
DeepEval-native version of the calibration; the numbers are a fresh measurement, not a
reproduction of the hand-built judge. Two deliberate differences from the hand-built judge:
it also sees the diff3 conflict block (more-informed), and it drops empty-region pairs from
*either* source (see lineage), where the historical n=310 dropped only xlsx-empty pairs.

Population lineage (consistent with the 627 breakdown above):

```
627  (row x tool) pairs with a 0/1 desirability label          [data.load_manual_labels]
 |   -253  punts        (lab.is_punt: tool left the conflict unresolved = a detection
 |                       event, not a resolution -- a DATA FACT)
374  non-punt desirability pairs
 |   -71   empty regions (candidate or developer empty after extraction, ANY source:
 v                       xlsx deletion, or a file region the anchor lost to an import
303  judgeable cases     repack/rename -- a JUDGEABILITY filter)
     -> fed to the GEval judge
```

The historical hand-built calibration used n=310 (it dropped only the 64 xlsx-empty
pairs); the DeepEval filter additionally drops ~7 file-source empty regions (the anchor
lost the developer region to a repack/rename, or a tool's output region was empty), giving
n=303. Filtering is in `evaluation/dataset.py` (two conditions, documented inline).

**Result (n=303, judge = claude-sonnet-4-6, threshold 0.5):**

- accuracy 76.9%, **precision 100.0%**, recall 61.7%  (TP113 FP0 TN120 FN70).
- The GEval judge is *even more* conservative than the hand-built one: zero false accepts
  on this set, so an `ACCEPTABLE` verdict is fully trustworthy; the cost is recall (it
  under-credits acceptable alternatives), so every solver/tool rate it produces is a
  conservative lower bound.

**Same-set comparison (hand-built vs GEval, both on the identical 303 set).** Recomputed
zero-API from the stored per-pair verdicts (`outputs/judge_calibration/calib_20260609_164106.jsonl`,
310 desirability records, intersected with the 303 GEval set; the 7 dropped pairs are empty-region
drops, none of them among the 8 false accepts):

| judge | n | precision | recall | TP/FP/TN/FN |
|---|---|---|---|---|
| hand-built | 303 | 92.9% | 56.8% | 104 / 8 / 112 / 79 |
| GEval ①    | 303 | **100.0%** | 61.7% | 113 / 0 / 120 / 70 |

So "92.9% -> 100%" is a **genuine same-set gain**, not an artifact of different filtering: on the
identical 303 calibration set, GEval's logprob-weighted scoring drives all 8 false accepts to 0
(FP 8 -> 0). (The hand-built judge's precision is coincidentally identical, 92.9%, on its native 310
and on this 303 subset.)

**Input-fidelity robustness check (`evaluation/audit_input_fidelity.py`).** The judge
validation surfaced a ground-truth *extraction* limitation rather than a judge defect:
anchor-based region extraction loses the developer/tool region when the developer reordered
or renamed the block (e.g. alphabetised imports), and a minority of xlsx fallback snippets
were hand-elided with `...`. Restricting to inputs with no known fidelity defect (n=281)
leaves precision essentially unchanged and lifts recall:

| subset | n | precision | recall |
|---|---|---|---|
| current run (empty-region filter) | 303 | 100.0% | 61.7% |
| no-known-fidelity-defect subset   | 281 | 98.3%  | 70.1% |

So the judge's high precision is **not** an artifact of polluted inputs (it holds at
98-100% under every filter), and the depressed recall is partly input-fidelity artifacts
(lost regions, elided snippets), not judge behaviour. The main conclusion -- a
high-precision, conservative judge -- is stable.

**Scope notes.**
- Dataset B (re-scoring the LLM solver outputs through this DeepEval suite, including the
  `StructuralValidity` metric) is now done -- see "DeepEval Solver Results (current)" below. The
  older hand-built-judge solver tables are retained under "Historical Milestone (superseded)".
- A deeper fix of the anchor extraction was deliberately declined: it would change the
  extraction every result in this file depends on, invalidating the committed 2026-06-09
  milestone for a subset that the clean-subset check shows does not move the conclusion.
  The extraction limitation is recorded here and in Limitations rather than fixed.

## Standalone-Valid Calibration

Standalone-valid is a separate, independent question: whether a candidate is a
reasonable merge judged from base/left/right alone, without the developer answer.
It does not compare against the developer resolution, so its conclusions are
independent of the developer-match results.

On a 40-item human-labeled blind sample:

- false conflicts (n=20): accuracy 85%, precision 88.2%, recall 93.8%
  (TP15 FP2 TN2 FN1);
- true conflicts: not used as a correctness metric, because a true conflict has
  no context-free correct answer (the choice depends on developer intent).

Only the false-conflict number is a substantive correctness figure.

## DeepEval Solver Results (current)

This is the Dataset B work: the LLM solver's own resolutions (Scheme A, forced resolution)
scored by the **validated ① GEval judge** and the **② StructuralValidity metric**
(`evaluation/run_solver_eval.py`). These numbers supersede the hand-built-judge solver tables
(now under "Historical Milestone (superseded)").

**Population (extends the Scheme-A trunk by one step).** The 72 Scheme-A comparable scenarios
lose 5 with an empty developer region (`ok`+empty `dev_region`: 1 true `vavr@abff73e3` + 4 false
`RxJava@45c9dc85`, `async-http-client@4999b8dd`, `halo@57c0f803`,
`incubator-shardingsphere@7fe148b3`), giving **67 Dataset B scenarios (49 true / 18 false)**.
Fed to both providers: 132 records (openai 67, gemini 65 -- gemini's 2 honest empties on
jedis/jjwt drop out), i.e. **96 true / 36 false** provider-level records.

**① developer-match (validated GEval judge, threshold 0.5):**

| conflict type | OpenAI | Gemini | pooled |
|---|---|---|---|
| **true** (headline) | 27/49 = 55.1% | 29/47 = 61.7% | **56/96 = 58.3%** |
| false | 12/18 = 66.7% | 11/18 = 61.1% | 23/36 = 63.9% |

The true-conflict **58.3%** is the current headline. It is *lower* than the old hand-built
62-66% by design: the GEval judge is stricter (precision 100% vs 92.9%, zero false accepts), so it
under-credits more -- a more conservative, more defensible lower bound. (It is also a lower bound in
a second sense: it counts only developer-matching resolutions, not "valid but different" ones, since
the standalone judge was deliberately not included -- see Standalone-Valid Calibration.)

**② structural validity (deterministic, no LLM):**

- true conflicts: 92/96 = **95.8%** (4 fail); false: 35/36 = 97.2% (1 fail).
- The 4.2% true-conflict failures are all retries-exhausted cases (`n_rounds=4`, never reached a
  valid resolution within the budget): 3 javalang parse failures (frontend-maven-plugin, jadx,
  web3j) + 2 duplicate-declaration (presto, both providers). **4 of the 5 ②-failures were accepted
  by ①** -- the LLM judge waved through code that does not parse. This is the concrete evidence that
  structural validity must be a deterministic metric, independent of the LLM judge.

**① LLM vs SOTA tools, same judge, coverage-fair (`scripts/compare_tools_geval.py`).** Both the
LLM and the 5 ConflictBench tools scored by the *same* ① GEval judge (apples-to-apples), on the
67-scenario reconstructable-Java overlap (49 true), under the overall convention (a tool punt or
absent resolution = miss, since the LLM almost always resolves):

| true conflicts (n=49) | among-resolved | overall | punt |
|---|---|---|---|
| LLM Gemini   | 29/47 = 61.7% | 29/49 = **59.2%** | 0 |
| LLM OpenAI   | 27/49 = 55.1% | 27/49 = **55.1%** | 0 |
| AutoMerge    | 18/38 = 47.4% | 18/49 = 36.7% | 10 |
| JDime        | 17/31 = 54.8% | 17/49 = 34.7% | 16 |
| IntelliMerge | 13/27 = 48.1% | 13/49 = 26.5% | 22 |
| FSTMerge     |  6/21 = 28.6% |  6/49 = 12.2% | 18 |
| KDiff3       |  2/4  = 50.0% |  2/49 =  4.1% | 45 |

Among-resolved, the LLM and the strongest tool are close (Gemini 61.7% vs JDime 54.8%); the gap
opens entirely on **coverage**: tools abstain heavily (KDiff3 punts 45 of 49, IntelliMerge 22,
JDime 16, AutoMerge 10) while the LLM under Scheme A never punts. Under the coverage-fair overall
convention the LLM (55-59%) clears the strongest tool (AutoMerge 36.7%) by ~18-22 points. This is
the applicability claim: the LLM's edge is not "slightly more accurate" but "still produces a
gradeable resolution where structured tools give up."

## Number provenance: how every reported figure is derived

All 93 reconstructable Java scenarios are fed to each LLM. The 72 / 50 / 47 below
are SCORING subsets (cases we can reliably grade), not an input sample: the model
answers all 93; we simply cannot batch-grade 21 of them.

```
SHARED TRUNK  (input pipeline; all scenarios pass through here)
--------------------------------------------------------------
  180  textual conflict scenarios (ConflictBench)
   |    -74  non-Java           (Java-only scope; syntax guard is Java-specific)
  106  Java scenarios
   |    -13  add/delete/rename  (no single-file 3-way content conflict to replay)
   93  reconstructable Java
        INPUT: all 93 are fed to EACH LLM (2 providers x 2 schemes).
        Everything below is SCORING filtering, NOT input sampling.
   |
   +--------------------------------+
   |                                |
SCHEME A (primary)               SCHEME B (robustness)
forces a resolution on all       lets the model punt true conflicts
   |                                |
  93  fed in                      93  fed in
   |   -21 ungradeable             |   -24 leave the comparable set
   |    (20 anchor_not_unique      |    (21 ungradeable, same guards,
   |     + 1 EOL no_conflict)      |     + gemini punts 5 / openai 1;
   |                                |     common = the intersection)
  72  comparable                  69  comparable
   |    = 50 TRUE + 22 FALSE       |    = 47 TRUE + 22 FALSE
   |                                |
  50  TRUE   <- milestone        47  TRUE
  22  FALSE  (also measured)      22  FALSE
```

**Dataset B (current) extends the Scheme-A branch by one step:** the 72 comparable scenarios
lose 5 with an empty developer region (1 true `vavr` + 4 false) -> **67 Dataset B scenarios
(49 true / 18 false)**, the set scored by the GEval suite in "DeepEval Solver Results (current)".
The `50 TRUE` / `47 TRUE` figures below belong to the hand-built-judge milestone and are retained
as historical (see the superseded banner below).

### The denominator is fixed by the LLMs, not the tools

A scenario enters the comparable set iff BOTH LLMs produced a gradeable resolution
(`status=resolved`, `dev_status=ok`). The 5 tools are then scored on that fixed
set; a tool that punts (leaves conflict markers) or has no recorded output counts
as a MISS. This is the fair convention when one side may abstain: fix the
denominator by the side that always answers, and count the other side's
abstention as a failure rather than shrinking the denominator.

One asymmetry to keep in mind: a tool punt stays in the denominator as a miss, but
an LLM punt in Scheme B removes that scenario from the denominator. So Scheme B's
LLM rates sit on a self-selected "resolvable" subset, which is why Scheme A
(no gating, forces a resolution on all 50 true conflicts) is the PRIMARY scheme
and Scheme B is a robustness check.

### Both conflict types are measured; the headline uses true conflicts

True conflicts are the hard case (overlapping edits requiring judgement); false
conflicts (compatible edits) should auto-merge, so beating tools there is less
telling. Both are reported; the resume headline quotes the true-conflict row.

### True-conflict developer-match (Scheme A, n=50) — historical, hand-built judge

> **⚠️ Historical milestone (hand-built judge) — superseded.** This table and the false-conflict
> table below use the *old hand-built judge* on the n=50/72 milestone scoring. They are kept for
> traceability; the **current** developer-match and tool-comparison numbers (validated GEval judge,
> Dataset B) are in **"DeepEval Solver Results (current)"** above. Do not quote the 62-66% / ≤52%
> figures as current.

| solver / tool | our judge (single-instrument) | human-label (tools) | punts |
|---|---|---|---|
| LLM Gemini   | 32/50 = 64.0% | --    | --  |
| LLM OpenAI   | 31/50 = 62.0% | --    | --  |
| AutoMerge    | 20/50 = 40.0% | 52.0% | 11  |
| JDime        | 19/50 = 38.0% | 48.0% | 17  |
| IntelliMerge | 13/50 = 26.0% | 32.0% | 22  |
| FSTMerge     |  8/50 = 16.0% | 26.0% | 18  |
| KDiff3       |  1/50 =  2.0% |  6.0% | 46  |

Scheme B (n=47): Gemini 31/47 = 66.0%, OpenAI 30/47 = 63.8%; strongest tool
(human-label) AutoMerge 53.2%.

Two instruments: `human-label` scores the tools with ConflictBench's (lenient)
human labels; `single-instrument` scores BOTH the LLM and the tools with our
Claude judge (apples-to-apples). The headline uses the human-label tool column --
the view most generous to the tools -- and the gap only widens under the single
instrument (strongest tool AutoMerge drops to 40.0%). Tool resolutions come from
the xlsx tool snippets recorded by ConflictBench, not from locally re-run tools;
the LLM advantage on true conflicts comes largely from tools abstaining (KDiff3
punts 46 of 50).

### False-conflict developer-match — historical, hand-built judge

Measured too, with a weaker narrative (tools abstain less, so the gap is smaller):

- Scheme A (n=22): Gemini 13/22 = 59.1%, OpenAI 11/22 = 50.0%; tools at most 59.1%
  (human-label) / 22.7% (single-instrument).
- Scheme B (n=22): Gemini 13/22 = 59.1%, OpenAI 13/22 = 59.1%.

### Scheme A vs Scheme B agree

On scenarios graded in both schemes, the developer-match verdicts agree closely,
confirming that B (allowing punts) does not overturn A:

- Gemini: 67/69 = 97% agreement;
- OpenAI: 60/71 = 85% agreement (disagreements split both ways, no systematic
  direction).

The two schemes feed different prompts and are independent model calls, so a
resolution need not be byte-identical across them; what matters is that the graded
outcome is stable. The measuring instrument's reliability is the judge calibration
above.

### Resume headline mapping

**Current (DeepEval, use these).** True-conflict developer-match **58.3%** (validated GEval judge,
Dataset B, n=96); vs SOTA tools under the same judge + coverage-fair convention, LLM **55-59%** vs
strongest tool AutoMerge **36.7%** (n=49 true, 67-scenario overlap). Quality claim uses 58.3%;
applicability claim uses the tool comparison + the coverage evidence (tools punt 25-90%, LLM punt=0).

**Historical (hand-built judge, do not quote as current).** "true conflicts ~63% vs <=52%" = LLM
62-66% (A: 62.0/64.0, B: 63.8/66.0) vs the strongest traditional tool 52.0% (AutoMerge, human-label,
Scheme A). Superseded by the GEval numbers above.

## Key Findings

- On true conflicts, under the validated GEval judge + coverage-fair convention, the LLMs (55-59%)
  beat every traditional tool (strongest AutoMerge 36.7%), mainly because tools abstain or leave
  conflicts unresolved (KDiff3 punts 45 of 49) while the LLM under Scheme A always attempts a
  resolution. Among-resolved the gap is small (Gemini 61.7% vs JDime 54.8%); the LLM's real edge is
  coverage, not raw accuracy.
- Structural validity (②) is 95.8% on true conflicts; the 4.2% that fail are retries-exhausted
  cases. Crucially, **① (the LLM judge) accepted 4 of the 5 structurally-invalid resolutions** --
  the LLM judge is unreliable for structural correctness, which is why ② must be a deterministic,
  independent metric.
- Schemes A and B agree closely on developer-match (Gemini 97%, OpenAI 85%), so forcing the model
  to declare conflict-ness first (B) does not change the aggregate result; B's punts are rare but
  precise (all on true conflicts). B was therefore not re-scored through DeepEval (low marginal info).
- Self-reported confidence is not a reliable desirability predictor.
- Gemini was generally steadier than OpenAI on final validity in the recorded runs.

## Limitations

- The developer-match judge is conservative and under-credits acceptable alternatives (GEval recall
  61.7%; hand-built 55.6%), so every reported rate is a lower bound.
- LLM outputs do not have independent human labels, so some judge-style bias cannot be fully ruled
  out (the judge is a different vendor from both solvers, which mitigates self-preference).
- The standalone-valid (no-reference) judge was deliberately *not* included in the DeepEval suite: it
  has no ground truth to validate against, so it would add an unverifiable judge. Consequently the
  58.3% counts only developer-matching resolutions, not "valid but different" ones -- a further
  reason it is a conservative lower bound.
- The LLM-vs-tools comparison is on the 67-scenario reconstructable-Java overlap (49 true), a subset
  of the full benchmark; tool resolutions come from ConflictBench's recorded xlsx snippets, not
  locally re-run tools.
- Anchor-based developer extraction excludes 20 scenarios whose region cannot be
  uniquely located; these split into four causes (boundary_edge, duplicate_context,
  adjacent_block_marker, rewrite_vanished) detailed in DATA.md. The guard excludes
  rather than guesses, so the denominator is a conservative subset, not a biased one.
- `javalang` checks syntax, not full Java compilation. For multi-block files where the spliced file
  still carries other blocks' markers, ② degrades to a marker-only check (no whole-file parse).
- Standalone-valid is meaningful only for false conflicts.
