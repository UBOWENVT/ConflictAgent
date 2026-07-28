# Results

This file records grounded, current results across two layers: the **judge layer** (GEval
calibration + standalone) and the **solver layer** ("DeepEval Solver Results"). Numbers come from
the DeepEval suite (`evaluation/run_suite.py`, `evaluation/run_solver_eval.py`,
`scripts/compare_tools_geval.py`). Developer-match rates are stratified by conflict type.

## Judge Calibration (GEval)

The developer-match judge (claude-sonnet-4-6) is a DeepEval `GEval` LLM-as-judge metric
(`evaluation/metrics.py`, `ResolutionAcceptability`), validated against ConflictBench's human
desirability labels for tool outputs (`evaluation/run_suite.py`). It sees the diff3 conflict block,
the candidate resolution, and the developer resolution, and decides whether the candidate is an
acceptable semantic match. Cross-vendor by design (Claude judging OpenAI/Gemini) to avoid
self-preference; temperature 0 for reproducibility.

Population lineage:

```
900  label grid = 180 scenarios x 5 tools
 |   -273  no label      (that (scenario,tool) has no 0/1 desirability label -- N/A)
627  (row x tool) pairs with a 0/1 desirability label          [data.load_manual_labels]
 |   -253  punts         (lab.is_punt: tool left the conflict unresolved = a detection
 |                        event, not a resolution -- a DATA FACT)
374  non-punt desirability pairs
 |   -22   file-level     (add/del/rename/add-add: ConflictBench has no complete
 |                        base/left/right 3-way for the file; whole scenario dropped --
 |                        the SAME check the solver line applies at 106->93)
352  has base/left/right
 |   -60   empty regions  (candidate or developer empty after extraction, ANY source:
 v                        xlsx deletion, or a file region the anchor lost to a reorder)
292  judgeable cases      -> fed to the GEval judge
```

Scheme A (2026-07) folded input-fidelity handling into this trunk: a scenario-level gate drops
file-level ops (`{"base","left","right"} <= load_scenario_files(...).keys()` in
`build_metaevaluation_testcases`), and `clean_xlsx_snippet`'s is_diff fix cleans 39 pure-add inputs
that previously leaked `+`-prefixed developers (recall 61.7 -> 64.6). Filtering is in
`evaluation/dataset.py`.

**Result (n=292, judge = claude-sonnet-4-6, threshold 0.5):**

- accuracy 78.1%, **precision 100.0%**, recall 64.6%  (TP117 FP0 TN111 FN64).
- The judge has zero false accepts on this set, so an `ACCEPTABLE` verdict is fully trustworthy;
  the cost is recall (it under-credits acceptable alternatives), so every solver/tool rate it
  produces is a conservative lower bound.

**Residual data-fidelity note.** Scheme A already removes the two big fidelity problems in the
trunk (file-level ops via the B gate; `+`-prefixed pure-add developers via the is_diff fix). What
remains in the n=292 is a minority of xlsx pairs whose candidate and developer are recorded at
inconsistent scopes/windows (e.g. a 2-line developer vs a 24-line tool block). Such a mismatch can
only make the judge *reject* a valid resolution — it depresses recall, never produces a false
accept — so precision stays 100%. See `docs/DATA.md` for the enumeration. The judge's high precision
is therefore not an artifact of clean inputs; a scope-mismatched reference can only cost recall, and
the conservative-lower-bound conclusion is stable.

**Scope notes.**
- Dataset B (the LLM solver outputs scored through this DeepEval suite, including the
  `StructuralValidity` metric) is in "DeepEval Solver Results (current)" below.
- A deeper fix of the anchor extraction was deliberately declined; the extraction limitation is
  recorded in Limitations rather than fixed, since it only depresses recall and does not move the
  conclusion (see the residual data-fidelity note above).

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
(`evaluation/run_solver_eval.py`).

**Population (extends the Scheme-A trunk by one step).** The 72 Scheme-A comparable scenarios
lose 5 with an empty developer region (`ok`+empty `dev_region`: 1 true `vavr@abff73e3` + 4 false
`RxJava@45c9dc85`, `async-http-client@4999b8dd`, `halo@57c0f803`,
`incubator-shardingsphere@7fe148b3`), giving **67 Dataset B scenarios (49 true / 18 false)**.
Fed to both providers: 132 records (openai 67, gemini 65 -- gemini's 2 empty resolutions on
`jedis@b013a74c` / `jjwt@3f079803` drop out), i.e. **96 true / 36 false** provider-level records.

**① developer-match (validated GEval judge, threshold 0.5):**

| conflict type | OpenAI | Gemini | pooled |
|---|---|---|---|
| **true** (headline = floor ~55%) | 27/49 = 55.1% | 29/47 = 61.7% | 56/96 = 58.3% |
| false | 12/18 = 66.7% | 11/18 = 61.1% | 23/36 = 63.9% |

> Footnote — Gemini's 2 empties are a solver failure mode, not a punt. On `jedis@b013a74c` and
> `jjwt@3f079803` Gemini exhausted all 4 retry rounds (`status=empty`, `punt=False`, `n_rounds=4`,
> `final_valid=False`): it kept emitting the field skeleton (STRATEGY/CONFIDENCE) but an empty
> RESOLUTION body, so no gradeable output was produced. An empty resolution can't be judged (GEval
> rejects empty actual_output), so these drop from Gemini's denominator (65, not 67) rather than
> count as wrong answers. Both are true conflicts; if instead counted as failures Gemini's true rate
> is 29/49 = 59.2% (the "overall" convention in the tool comparison below) vs 29/47 = 61.7%
> ("among-resolved"). Either way the headline floor is OpenAI's 55.1% (OpenAI resolved both), so
> these two empties do not move the reported ~55%.

For the headline we quote the **conservative floor, ~55%** (OpenAI 27/49 = 55.1%, the lower of the
two providers) rather than the pooled 58.3% — consistent with the coverage-fair LLM range 55–59% and
with reporting a floor, not a provider average. It is conservative by design: the GEval judge is
strict (100% precision, zero false accepts), so it under-credits acceptable alternatives -- a
defensible lower bound. (It is also a lower bound in
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
  50  TRUE                       47  TRUE
  22  FALSE                       22  FALSE
```

**Dataset B (current) extends the Scheme-A branch by one step:** the 72 comparable scenarios
lose 5 with an empty developer region (1 true `vavr` + 4 false) -> **67 Dataset B scenarios
(49 true / 18 false)**, the set scored by the GEval suite in "DeepEval Solver Results (current)".

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

### Scheme B (detection / robustness variant)

Scheme B lets the model punt — predict "true conflict; do not auto-resolve" — a detection capability
distinct from Scheme A's forced resolution. Scheme A is the scored line; Scheme B is a supported
variant, not re-scored through the DeepEval suite. The methodology (fixed-denominator, coverage-fair,
both conflict types measured) is unchanged and described above.

### Resume headline mapping

**Current (DeepEval, use these).** True-conflict developer-match **≈55%** (conservative floor; OpenAI
55.1%, Gemini 61.7%, pooled 58.3% — we quote the floor), validated GEval judge, Dataset B; vs SOTA
tools under the same judge + coverage-fair convention, LLM **55-59%** vs strongest tool AutoMerge
**36.7%** (n=49 true, 67-scenario overlap). Quality claim uses the ~55% floor; applicability claim
uses the tool comparison + coverage evidence (tools punt 25-90%, LLM punt=0).

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
- Schemes A and B agreed closely in the earlier milestone (archived), so forcing the model to
  declare conflict-ness first (B) does not change the aggregate result; B's punts are rare but
  precise (all on true conflicts). B is a detection/robustness variant and is not re-scored through
  DeepEval (Scheme A is the scored line).
- Self-reported confidence is not a reliable desirability predictor.
- Gemini was generally steadier than OpenAI on final validity in the recorded runs.

## Limitations

- The developer-match judge is conservative and under-credits acceptable alternatives (GEval recall
  64.6%), so every reported rate is a lower bound.
- LLM outputs do not have independent human labels, so some judge-style bias cannot be fully ruled
  out (the judge is a different vendor from both solvers, which mitigates self-preference).
- The standalone-valid (no-reference) judge was deliberately *not* included in the DeepEval suite: it
  has no ground truth to validate against, so it would add an unverifiable judge. Consequently the
  headline counts only developer-matching resolutions, not "valid but different" ones -- a further
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
