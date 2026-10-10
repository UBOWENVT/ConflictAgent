# Agent Harness (Inspect AI + Docker sandbox)

This is the agent setting of ConflictAgent. The solver works on the same Dataset B conflicts as
the single-shot pipeline, but as a tool-using agent inside a sandbox: it locates context itself,
edits the conflicted file itself, runs a syntax check itself, over many turns. The question is how
the agent setting compares with the single-shot setting on the same conflicts, under the same
judge: resolution quality, cost, and where each one fails.

The two settings differ in more than the tools. They also differ in the context the model sees,
the number of turns, the prompt, and the output format (an edited file instead of a returned
snippet). Results therefore compare the two *settings*. A claim about one tool would need an
ablation.

> Status: the harness, the sandbox and the scoring rules below are in place and tested with a
> scripted mock model. Results are reported once the scored runs exist.

## Layout

```text
harness/
  task.py          Inspect task: dataset + agent + tools + sandbox + scorer + limits
  dataset.py       the fixed 67 Dataset B scenarios -> Inspect Samples
  tools.py         view_file / replace_text / check_java, and the pre-agent workspace step
  scorers.py       deterministic scoring of the final file (no LLM judge)
  prompts.py       agent instructions
  export.py        Inspect logs -> run_eval.py-schema JSONL for the offline judge
  analyze.py       per-sample process metrics and token cost
  sandbox/         Dockerfile, compose.yaml, check_java.py (+ a byte-identical validate.py)
evaluation/run_unified_eval.py   one judge instance over several groups of resolutions
tests/harness/                   unit, mock end-to-end (local and Docker) tests
```

The harness has its own environment, because inspect-ai and the DeepEval scoring stack pin
incompatible dependency ranges:

```bash
python -m venv .venv-harness && .venv-harness/bin/pip install -r harness/requirements.txt
.venv-harness/bin/python -m pytest tests/harness            # needs Docker for the -m docker tests
.venv-harness/bin/inspect eval harness/task.py --model openai/gpt-5.4-2026-03-05
```

The judge runs afterwards in the original `.venv` (DeepEval 4.0.7), via
`evaluation/run_unified_eval.py`.

## Samples

- **Population.** The 67 scenario ids of `results/solver_eval_20260627_095221.jsonl`: 49 true and
  18 false conflicts, the same population as the single-shot Dataset B results.
- **The conflict file** is built exactly as the single-shot pipeline builds it:
  `merge.reconstruct_merged`, then `groundtruth.select_target_block`, then
  `agent._annotate_target`. The target block's `<<<<<<<` line carries `[[RESOLVE THIS CONFLICT]]`.
- **Files.** Each sample holds exactly four, at relative paths (`/workspace/...` in the container):
  - the tagged conflict file at its repository path;
  - `sides/base/<path>`, `sides/left/<path>`, `sides/right/<path>`.

  Only base, left and right are read to build a sample. The developer's resolution (the `child`
  file) is not read and never enters a sample or the sandbox.
- **Sample metadata** holds what the scorer needs and nothing developer-derived:
  - the scenario id and conflict type;
  - the conflict file's path, its number of blocks, and the target block's index;
  - the file text before and after the target block;
  - a hash of the tagged target block.

## Sandbox

The model gets a shell that can run arbitrary commands, so isolation comes from the container, not
from the prompt.

| Property | How |
|---|---|
| Fresh per sample | Inspect creates and removes one compose project per sample. |
| No network | `network_mode: none` |
| No credentials | No `environment` / `env_file` in `compose.yaml`. The container sees only the base image's variables. |
| No answers or data | The build context is `harness/sandbox/` only (`.dockerignore` admits 2 files). The image holds Python, javalang and the checker. |
| Not root | Runs as uid 1000 (`agent`). The checker in `/opt/harness` is root-owned. |
| Resource caps | 1 CPU, 1 GB memory, 256 processes. All capabilities dropped, `no-new-privileges`. |
| Pinned image | `python:3.12-slim` by digest, `javalang==0.13.0` |

`sides/` files are made read-only at sample start. This guards against accidental edits; it is not
a security boundary, and scoring never reads `sides/`.

Inspect's `local` sandbox runs the model's commands on the host, with the host environment and
`data/` in reach. It is used only by mock-model tests. `prepare_workspace()` refuses any model
other than `mockllm` when the sandbox is not a container.

Tests guard the four-file whitelist (paths and bytes), the metadata allowlist, an image scan for
`child` / `*.xlsx` / `.env` / `*.jsonl`, and the in-container checks run by a mock agent:
- `env` shows no credentials and no host variables;
- the user is non-root;
- the network is unreachable;
- `sides/` is not writable.

## Agent and tools

The agent is Inspect's `react` with four tools. `submit()` takes one sentence. **What is scored is
the conflict file left in the sandbox, not the submitted text.**

| Tool | Behavior |
|---|---|
| `bash` | Inspect built-in: `grep -n`, `diff` between the sides, etc. |
| `view_file(path, start, end)` | Numbered line range. At most 300 lines and about 12 KB per call, so output stays under Inspect's 16 KiB tool-output truncation. |
| `replace_text(path, old, new)` | Replaces one exact, unique occurrence, reading and writing raw bytes. Nothing else in the file changes; Inspect's `text_editor` rewrites the whole file and expands tabs. Not run in parallel. |
| `check_java(path)` | Runs `harness/sandbox/check_java.py` in the container. |

`check_java` gives the same verdict as the single-shot validator (`agent._validate`):
- **Fail** if the tagged region still has markers (the tag is present, a stray marker line, or a
  malformed region).
- **Single-block file:** pass if the whole file parses with javalang and has no duplicate
  declarations.
- **Multi-block file:** pass if exactly *original − 1* untouched regions remain; their markers are
  expected. As an informational signal (never a pass condition), it also reports whether the file
  parses with the remaining regions replaced by their left side.

One difference: `_validate` rejects an empty resolution, while `check_java` sees only the edited
file. Scoring treats an empty resolution as described below.

**Limits:** 60 messages, 10 minutes, 600,000 tokens per sample. Temperature 0. Reasoning effort is
left at each provider's default. `fail_on_error=0.05`; interrupted runs continue with
`inspect eval-retry`.

These were set after a first trial (10 scenarios × 2 models) that used 40 messages. That limit cut
off 3 of the 10 Gemini samples, which spent many steps looking for repository files and git that
the sandbox does not have. Two sentences were then added to the prompt: one stating that the four
files are all there is, and one giving the step budget. Both changes are generic (environment
facts and limits), not tied to any scenario. Trial runs are for debugging only and do not feed
any reported number.

**Models.** `openai/gpt-5.4-2026-03-05` and `google/gemini-3.5-flash`, the same ids as the
single-shot runs. Google now routes `gemini-3.5-flash` requests to `gemini-3.6-flash`: the
responses report `model_version: gemini-3.6-flash` (checked 2026-10-09), and Google's deprecation
page says the same. A same-day single-shot rerun sends the same id, so both settings get the same
served model. The June single-shot outputs came from the model before this routing.

## Scoring rules

These rules were fixed before the first real-model run.

### 1. Extracting the resolution

The original conflict file is *prefix + target block + suffix*. Given the final file:

| Extraction | Condition | Resolution |
|---|---|---|
| `exact` | The final file is *prefix + R + suffix*. Deleting the block together with its line break also counts. | `R` |
| `whitespace_only` | Outside the block, the file is equal to the original once whitespace within each line and trailing blank lines are ignored (tabs expanded, CRLF, final newline). | The final file's lines between the aligned prefix and suffix, unnormalized |
| `out_of_block` | The file changed outside the target block. | The lines between the last unchanged line before the block and the first unchanged line after it (diff alignment) |
| `not_extractable` | No conflict file, or the block cannot be located. | none |

The resolution is trimmed the way the single-shot pipeline trims its output: surrounding blank lines
and trailing whitespace are removed.

### 2. Outcomes

Each sample gets exactly one outcome. Denominators are fixed per model: **49 true / 18 false
conflicts**.

| Outcome | Meaning | Primary convention | Secondary convention |
|---|---|---|---|
| `gradeable` | A resolution was extracted (`exact` or `whitespace_only`), it is non-empty and marker-free | (1) judge | (1) judge |
| `empty` | The extracted resolution is empty | miss | excluded |
| `no_edit` | The target block is unchanged | miss | excluded |
| `unfinished` | The run stopped (a limit) with markers still in the resolution | miss | excluded |
| `markers` | Submitted with conflict markers in the resolution | miss, no judge call | miss |
| `out_of_block` | The file changed outside the target block | miss | (1) judge on the in-block resolution |
| `not_extractable` | The resolution cannot be located | miss | excluded |
| `error` | The sample itself errored | miss | excluded |

- Hitting a limit is not an outcome of its own: the scorer still runs and scores whatever is in the
  file.
- **Single-shot records get the same rules.** An API error is `error`, an empty resolution is
  `empty`, a resolution with markers is `markers`, anything else is `gradeable`. So the June
  Gemini empty outputs count as misses under the primary convention.
- **Headline rate:** the lower of the two providers, not a pooled rate. One table uses numbers
  from one run only.

### 3. (1) developer-match

The judge runs offline, after all runs, in one process: `evaluation/run_unified_eval.py`.
- **Inputs.** `harness/export.py` writes each agent sample as a `run_eval.py`-schema record. It
  carries the resolution and the developer region, recomputed from `child` exactly as
  `scripts/run_eval.py` computes it.
- **Test cases.** Every group goes through `evaluation.dataset.build_solver_testcases` unchanged.
  Before any judge call, each group's `input` and `expected_output` are checked byte-for-byte
  against the June group's.
- **One judge instance.** One GEval instance (Claude Sonnet 4.6, threshold 0.5, DeepEval 4.0.7)
  judges every group in a seeded shuffled order. Its evaluation steps are generated once, written
  to the output, and shared.
- **Three groups:** the agent runs, a same-day rerun of the single-shot code
  (`scripts/run_eval.py --scheme A --no-judge`, unchanged), and the 132 June resolutions.
  - June re-judged vs the frozen June verdicts measures judge drift.
  - The single-shot rerun vs June measures model drift.
  - Agent vs single-shot rerun is the main comparison, under an identical judge.
- **Why offline.** The judge is not called inside Inspect's scorer. GEval keeps the score and its
  evaluation steps on the metric instance, so concurrent scoring through a shared instance would
  cross verdicts silently.

### 4. (2) structural validity

The cleaned resolution is spliced back into the **original** conflict file and checked exactly as
in Dataset B:
- no markers in the resolution;
- the file parses (javalang);
- no duplicate declarations.

If other blocks still carry markers, only the marker check applies. Whether the agent's final file
parses as a whole is reported separately as a process metric, not as (2).

### 5. Process metrics

From the logs (`harness/analyze.py`):
- model calls, and tool calls per tool;
- tool errors, including argument-parsing errors, and truncated tool outputs;
- whether `check_java` ran before `submit`, and whether a failed check was later fixed;
- limits hit;
- tokens (input, cached, output, reasoning) and time.

Cost is tokens × list price, computed afterwards.
