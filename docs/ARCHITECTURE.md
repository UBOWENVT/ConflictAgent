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
  -> validate and retry

scripts/run_eval.py
  -> run agent per scenario/provider/scheme
  -> judge developer-match and standalone-valid
  -> compute detection, confidence buckets, trivial baselines

scripts/compare_tools.py
  -> compare LLM outputs with ConflictBench's five tools
```

## Core Modules

- `conflictagent/config.py`: paths, model IDs, retry limit, window size, scheme constants.
- `conflictagent/data.py`: xlsx loading, scenario metadata, manual labels, local file loading.
- `conflictagent/merge.py`: reconstruction of diff3 conflict files.
- `conflictagent/validate.py`: marker checks, block splicing, diff3 splitting, Java parsing, duplicate declarations.
- `conflictagent/groundtruth.py`: target-block selection and anchor-based region extraction.
- `conflictagent/solver.py`: prompt construction, windowing, solver output parsing.
- `conflictagent/agent.py`: generate-validate-retry loop.
- `conflictagent/judge.py`: developer-match and standalone-valid judge prompts.
- `conflictagent/llm.py`: provider-agnostic wrapper for OpenAI, Gemini, and Anthropic.

## Entrypoints

- `scripts/fetch_data.py`: download xlsx and reconstructable scenario files.
- `scripts/smoke_test_llm.py`: verify provider keys and model IDs.
- `scripts/run_eval.py`: main evaluation script.
- `scripts/calibrate_judge.py`: calibrate developer-match judge against tool labels.
- `scripts/sample_standalone_calibration.py`: generate and score a human calibration sample for standalone-valid.
- `scripts/compare_tools.py`: compare LLMs against the five ConflictBench tools.
- `scripts/merge_recovery.py`: fold recovered transient-failure runs into complete eval files.
- `scripts/check_determinism.py`: spot-check temperature-0 solver reproducibility.

## Validation Boundary

The agent validates only with signals available at inference time:

- the candidate must not contain conflict markers;
- the spliced file must parse as Java when all conflict blocks are resolved;
- duplicate declarations are rejected as likely over-scoped output.

If a file still contains other unresolved conflict blocks after replacing the target block, full-file
Java parsing is not possible. In that multi-block case, the agent accepts a marker-free target
resolution and leaves semantic scoring to evaluation.

## Evaluation Boundary

Evaluation may use:

- `child` developer files;
- xlsx human labels;
- tool strategy/desirability labels;
- calibrated judge outputs.

None of those signals can flow back into `agent.resolve`.
