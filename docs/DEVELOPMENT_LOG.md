# Development Log

This is a compressed history. The detailed vault log remains the chronological source, but this
repo-local summary keeps the project understandable without opening the vault.

## 2026-06-06

- Project scoped as an engineering artifact for resume/interview use.
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

- Full developer-match judge calibration completed: n=310, precision 92.9%.
- `compare_tools.py` compared LLM solvers with the five ConflictBench tools.
- Main result established: on true conflicts, LLM solvers score about 62-66% versus <=52% for the
  strongest traditional tool under the human-label tool view.
- Resume bullets were updated with grounded numbers.

## 2026-06-16 Cleanup

- Repo-local docs were consolidated under `docs/`.
- README was rewritten to reflect the completed project and current metrics.
- The old single-shot baseline entrypoint was deprecated because the project no longer uses that
  baseline as a primary comparison.
