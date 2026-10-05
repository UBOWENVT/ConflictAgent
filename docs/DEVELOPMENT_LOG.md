# Development Log

This is a compressed history of the project. Numbers under dated entries are the figures of that
time; current results are in `docs/RESULTS.md`.

## 2026-06-06

- Project scoped as an evaluation harness on top of ConflictBench, not a new benchmark.
- Initial architecture established: agent loop without ground truth; offline judge with ground truth.
- Data loading, full-file fetch, diff3 reconstruction, syntax validation, and initial agent loop
  were implemented.

## 2026-06-07

- Full Java run showed modern LLMs usually produce syntactically valid first attempts.
- Project focus shifted from retry-loop syntax delta to semantic desirability and calibrated judging.
- Ground-truth extraction moved from xlsx snippets to real `child` files where possible.
- Tool-output handling and detection labels were audited; four detection errata were encoded.

## 2026-06-08

- Solver moved from whole-file prompting to windowed prompting.
- Prompt schemes A and B were introduced.
- `run_eval.py` gained trivial baselines, confidence buckets, standalone-valid, and A/B support.
- Full A/B runs completed.
- Standalone-valid calibration showed it is meaningful only for false conflicts.
- Over-scoped solver output was identified as a form-validation issue.

## 2026-06-09

- Full developer-match judge calibration completed with the hand-built judge (superseded; see the
  archive at the end of this file).
- `compare_tools.py` compared LLM solvers with the five ConflictBench tools.
- First LLM-vs-tools result under the hand-built judge (superseded; see the archive at the end of
  this file).

## 2026-06-16 Cleanup

- Repo-local docs were consolidated under `docs/`.
- README was rewritten to reflect the completed project and current metrics.
- The old single-shot baseline entrypoint was deprecated because the project no longer uses that
  baseline as a primary comparison.

## 2026-06 (late) to 2026-07: DeepEval reimplementation + pipeline hardening

- Judge reimplemented from the hand-built developer-match judge to a DeepEval `GEval` metric
  (`evaluation/metrics.py`, validated by `evaluation/run_suite.py`). Current judge calibration:
  Dataset A n=292, precision 100%, recall 64.6% (see `docs/RESULTS.md`).
- Solver scoring moved to the DeepEval suite (`evaluation/run_solver_eval.py`,
  `scripts/compare_tools_geval.py`); Dataset B = 67 scenarios (49 true / 18 false).
- Judge-line input pipeline hardened (Scheme A): scenario-level file-level gate + `is_diff` fix in
  `clean_xlsx_snippet` (see `docs/DATA.md`).

## Historical numbers archive — hand-built judge milestone (2026-06-09), superseded

Kept only for provenance; **not** part of current results. Raw artifacts are local (gitignored),
so this is the map to them:

- **Hand-built judge calibration:** n=310, accuracy 70.6%, precision 92.9%, recall 55.6%.
  Same-set vs GEval (both on the current n=292): hand-built 92.9% / 57.5% (FP=8) → GEval
  100% / 64.6% (FP=0). Verdicts: `outputs/judge_calibration/calib_20260609_164106.jsonl`;
  produced by `scripts/calibrate_judge.py`.
- **Hand-built solver developer-match (true conflicts):** Scheme A milestone n=50, ~62–66%
  developer-match vs strongest tool ≤52% (human-label tool view); a false-conflict table; and
  Scheme A vs Scheme B agreement ~97% / ~85%. Eval outputs: `outputs/eval/_archive/eval_B_*.jsonl`
  (and the `eval_A_*` runs); produced by `scripts/run_eval.py --scheme A|B` and
  `scripts/compare_tools.py`.

Why superseded: the GEval reimplementation drives false accepts to zero (precision 92.9%→100% on
the same set) and the current solver numbers are scored by that validated judge, so the hand-built
tables would be a second, weaker measurement of the same thing.
