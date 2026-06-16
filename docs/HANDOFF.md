# Handoff

Read in this order:

1. [../README.md](../README.md)
2. [SPEC.md](SPEC.md)
3. [ARCHITECTURE.md](ARCHITECTURE.md)
4. [RESULTS.md](RESULTS.md)
5. [PROMPTS.md](PROMPTS.md)

## Current State

The project is complete enough for resume/interview use. The main code path and final results are
in place. `data/` and `outputs/` are local artifacts and are not committed.

## Recovery Snapshot

Commit `dfb7a90` preserves the pre-cleanup snapshot with:

- longer retry/backoff settings for transient Gemini 503 failures;
- `run_eval.py --only-ids` for recovering failed scenarios.

Use this commit as the clean recovery point before documentation cleanup.

## Optional Future Work

- Add unit tests around prompt parsing, diff3 splitting, and duplicate declaration detection.
- Tighten standalone-valid judging for false conflicts.
- Add a supplementary final-valid-only results table.
- Consider compiling Java snippets with project context only if a future goal requires stronger
  validation than `javalang` parsing.
