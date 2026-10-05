# Architecture

## Data Flow

```text
scripts/fetch_data.py
  -> data/ConflictBench.xlsx
  -> data/scenarios/{project}__{commit}/{base,left,right,child,tool}

conflictagent.data
  -> Scenario / ManualLabel records
  -> full scenario files

conflictagent.merge
  -> git merge-file --diff3
  -> reconstructed merged file with conflict markers

conflictagent.groundtruth
  -> select target conflict block using xlsx MERGED snippet
  -> extract developer/tool resolution regions from resolved files

conflictagent.solver
  -> build windowed prompt
  -> call OpenAI/Gemini solver
  -> parse structured output

conflictagent.agent
  -> annotate target block
  -> call solver
  -> splice resolution into full file
  -> validate and retry   (② structural gate, inference-time)

evaluation.dataset            (DeepEval test-case builder)
  -> build_metaevaluation_testcases: 900-cell label grid (180 scenarios x 5 tools), 627 labeled
     -> scenario-level 3-way gate (Scheme A: base/left/right present)
     -> is_diff-corrected xlsx snippet cleaning
     -> n = 292 gradeable meta-eval cases (Dataset A)

evaluation.metrics            (the two DeepEval metrics)
  -> ① ResolutionAcceptability (GEval, DeepEval built-in, our criteria)
  -> ② StructuralValidity      (our custom BaseMetric, reuses validate.py)

evaluation.run_suite          -> ③ judge meta-evaluation (① vs human labels on tool resolutions, n=292)
evaluation.run_solver_eval    -> Dataset B: ① + ② over the solver line
scripts/compare_tools_geval.py-> LLM vs ConflictBench's five tools, same ① judge
```

## Core Modules

- `conflictagent/config.py`: paths, model IDs, retry limit, window size, scheme constants.
- `conflictagent/data.py`: xlsx loading, scenario metadata, manual labels, local file loading.
- `conflictagent/merge.py`: reconstruction of diff3 conflict files.
- `conflictagent/validate.py`: marker checks, block splicing, diff3 splitting, Java parsing, duplicate declarations.
- `conflictagent/groundtruth.py`: target-block selection and anchor-based region extraction.
- `conflictagent/solver.py`: prompt construction, windowing, solver output parsing.
- `conflictagent/agent.py`: generate-validate-retry loop.
- `conflictagent/judge.py`: JUDGE_SYSTEM rubric (the calibrated v2 developer-match criteria). Now the SOURCE of the GEval criteria in `evaluation/metrics.py`; the standalone hand-built judge runner is historical (see DEVELOPMENT_LOG).
- `conflictagent/llm.py`: provider-agnostic wrapper for OpenAI, Gemini, and Anthropic.

### Evaluation layer (DeepEval)

- `evaluation/dataset.py`: builds DeepEval `LLMTestCase`s. `build_metaevaluation_testcases` applies the scenario-level 3-way gate (Scheme A) and the is_diff-corrected snippet cleaning; yields n=292 gradeable meta-eval cases from the 900-cell label grid (627 labeled).
- `evaluation/metrics.py`: the two metrics. ① `ResolutionAcceptability` = GEval (DeepEval built-in LLM-as-judge, our criteria lifted from `judge.py`). ② `StructuralValidity` = our custom `BaseMetric` subclass, deterministic, no LLM, reusing `validate.py`. ② reads the spliced full file from `test_case.metadata['spliced_file']`; ① ignores metadata.
- `evaluation/run_suite.py`: ③ judge meta-evaluation — runs ① over the labeled cases, confusion matrix vs human labels (precision/recall + disagreement dump).
- `evaluation/run_solver_eval.py`: Dataset B — runs ① + ② over the solver line, stratified by conflict type and provider. ② does NOT gate ①.
- `evaluation/build_complete_set.py`: assembles the solver-output complete set fed to `run_solver_eval`.
- `evaluation/audit_*.py`, `show_judge_inputs.py`, `trace_anchor_extraction.py`: input-fidelity / dev-region audits used to validate the pipeline.

## Entrypoints

Current (DeepEval evaluation):

- `scripts/fetch_data.py`: download xlsx and reconstructable scenario files.
- `scripts/smoke_test_llm.py`: verify provider keys and model IDs.
- `scripts/run_eval.py --scheme A --no-judge`: run the solver agent over all reconstructable Java scenarios and save each final resolution (`--no-judge` skips the script's legacy built-in judge).
- `evaluation/build_complete_set.py`: merge the solver runs into one record per scenario × provider.
- `scripts/verify_numbers.py`: recompute the reported figures from the frozen files in `results/` (no LLM calls).
- `evaluation/run_suite.py`: ③ judge meta-evaluation (① vs human labels, n=292 → P=100% / R=64.6%).
- `evaluation/run_solver_eval.py`: Dataset B — score solver outputs with ① + ②.
- `scripts/compare_tools_geval.py`: LLM vs the five ConflictBench tools under the same ① judge.
- `scripts/check_determinism.py`: spot-check temperature-0 solver reproducibility.

Historical (hand-built-judge era, superseded — kept for provenance, see DEVELOPMENT_LOG):

- `scripts/run_agent.py` (early loop-only runner), `scripts/calibrate_judge.py`, `scripts/sample_standalone_calibration.py`, `scripts/compare_tools.py`, `scripts/run_baseline.py`, `scripts/merge_recovery.py`; and `scripts/run_eval.py`'s own judge summary (when run without `--no-judge`).

## Validation Boundary

The agent validates only with signals available at inference time:

- the candidate must not contain conflict markers;
- the spliced file must parse as Java when all conflict blocks are resolved;
- duplicate declarations are rejected as likely over-scoped output.

If a file still contains other unresolved conflict blocks after replacing the target block, full-file
Java parsing is not possible. In that multi-block case, the agent accepts a marker-free target
resolution and leaves semantic scoring to evaluation.

The same three checks are metric ②'s gen-time role. ② appears twice — an inference-time gate here (at most 4 rounds; if none passes, the last attempt is returned with `final_valid=False` rather than withheld) and a reported metric at eval time — but only on the solver line; the judge line (Dataset A) never builds a spliced full file, so ② does not run there.

## Evaluation Boundary

Evaluation may use:

- `child` developer files;
- xlsx human labels;
- tool strategy/desirability labels;
- ① GEval judge outputs (validated against human labels on tool resolutions: P=100% / R=64.6%, n=292).

None of those signals can flow back into `agent.resolve`.
