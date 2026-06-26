# Results

This file records grounded results from the completed 2026-06-09 milestone. All
developer-match rates are stratified by conflict type and computed by
`scripts/compare_tools.py` from the saved eval files; the numbers below supersede
an earlier un-stratified snapshot.

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
- The solver-line results below still rest on the *hand-built* judge; re-scoring the LLM
  solver outputs through this DeepEval suite (with the `StructuralValidity` metric) is the
  pending Dataset B work, not yet done.
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
  50  TRUE   <- headline          47  TRUE
  22  FALSE  (also measured)      22  FALSE
```

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

### True-conflict developer-match (Scheme A, n=50)

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

### False-conflict developer-match

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

"true conflicts ~63% vs <=52%" = LLM 62-66% (A: 62.0/64.0, B: 63.8/66.0) vs the
strongest traditional tool 52.0% (AutoMerge, human-label, Scheme A). Scheme B's
strongest tool is 53.2%, so "<=52%" is Scheme-A-specific; cross-scheme it is
<=~53%.

## Key Findings

- On true conflicts, both LLMs (62-66%) beat every traditional tool (<=52% under
  the tool-friendly human-label view), mainly because tools abstain or leave
  conflicts unresolved while the LLMs attempt a resolution.
- Schemes A and B agree closely on developer-match (Gemini 97%, OpenAI 85%), so
  forcing the model to declare conflict-ness first (B) does not change the
  aggregate result; B's punts are rare but precise (all on true conflicts).
- Modern solver models usually produce syntactically valid code on the first
  attempt, so retry is a safety loop, not the headline.
- Self-reported confidence is not a reliable desirability predictor.
- Gemini was generally steadier than OpenAI on final validity in the recorded runs.

## Limitations

- The developer-match judge is conservative and may under-credit acceptable
  alternatives (recall 55.6%), so reported rates are lower bounds.
- LLM outputs do not have independent human labels, so some judge-style bias
  cannot be fully ruled out (the judge is a different vendor from both solvers,
  which mitigates self-preference).
- Anchor-based developer extraction excludes 20 scenarios whose region cannot be
  uniquely located; these split into four causes (boundary_edge, duplicate_context,
  adjacent_block_marker, rewrite_vanished) detailed in DATA.md. The guard excludes
  rather than guesses, so the denominator is a conservative subset, not a biased one.
- `javalang` checks syntax, not full Java compilation.
- Standalone-valid is meaningful only for false conflicts.
