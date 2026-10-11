# Agent Harness (Inspect AI + Docker sandbox)

This is the agent setting of ConflictAgent. The solver works on the same Dataset B conflicts as
the single-shot pipeline, but as a tool-using agent inside a sandbox: it locates context itself,
edits the conflicted file itself, runs a syntax check itself, over many turns. The question is how
the agent setting compares with the single-shot setting on the same conflicts, under the same
judge: resolution quality, cost, and where each one fails.

"Single-shot" here means the existing pipeline (`conflictagent/agent.py`): the program builds one
prompt, the model returns the resolution in one call, and the program validates it and retries
with the validator's error, at most 4 attempts (1.1–1.2 calls per scenario in practice). It is not
the round-0 baseline discussed in the README.

The two settings differ in more than the tools. They also differ in the context the model sees,
the number of turns, the prompt, and the output format (an edited file instead of a returned
snippet). Results therefore compare the two *settings*. A claim about one tool would need an
ablation.

> Status: one full scored run, 2026-10-10. Results and limitations are at the end of this page.

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
the sandbox does not have. Two short notes were then added to the prompt: that the four files are
all there is (no repository, no git), and the step budget. Both changes are generic (environment
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

## Results (full run, 2026-10-10)

Every number below comes from the run outputs, through the commands in
[Reproducing the tables](#reproducing-the-tables). The logs and per-sample outputs are local
(gitignored).

### Runs

| Run | Size | Result | Cost |
|---|---|---|---|
| Agent, Docker sandbox | 67 scenarios × 2 models = 134 samples | 0 errors; 131 `gradeable`, 3 `empty` | $6.15 (GPT $2.36, Gemini $3.79), from logged tokens |
| Single-shot rerun, same day | 134 records (`scripts/run_eval.py --scheme A --no-judge`, unchanged code) | 0 errors, 0 empty | not logged; estimate under [Process and cost](#process-and-cost) |
| Unified scoring | 402 records in 3 groups (agent, single-shot rerun, June); 397 judge calls (the 5 empty resolutions are not judged) | 0 judge errors | — |

Before any judge call, the hard check passed: the agent's 131 and the rerun's 134 test cases have
the same `input` and `expected_output`, byte for byte, as the June cases.

"Gemini" is the id `gemini-3.5-flash` in all three groups. For the agent and the rerun it was
served by `gemini-3.6-flash` (see [Models](#agent-and-tools)); the June outputs came from the model
before that routing.

### (1) developer-match

Primary convention, fixed denominators: 49 true and 18 false conflicts per model.

| Group | GPT-5.4, true | Gemini, true | **Lower provider, true** | GPT-5.4, false | Gemini, false |
|---|---|---|---|---|---|
| Agent | 26/49 = 53.1% | 32/49 = 65.3% | **53.1%** | 13/18 = 72.2% | 11/18 = 61.1% |
| Single-shot rerun | 23/49 = 46.9% | 35/49 = 71.4% | **46.9%** | 12/18 = 66.7% | 11/18 = 61.1% |
| June single-shot, re-judged | 27/49 = 55.1% | 29/49 = 59.2% | 55.1% | 12/18 = 66.7% | 11/18 = 61.1% |

- **Without presto** (true conflicts, n = 48; see [Limitations](#limitations)): agent 26/48 = 54.2%
  and 32/48 = 66.7%; single-shot rerun 22/48 = 45.8% and 34/48 = 70.8%; June 26/48 = 54.2% and
  29/48 = 60.4%.
- **Secondary convention** (true conflicts; `empty` leaves the denominator): agent GPT 26/48 =
  54.2%, Gemini 32/47 = 68.1%; June Gemini 29/47 = 61.7%. The other rows are unchanged, because
  they have no excluded outcome.

### Agent vs single-shot, scenario by scenario

Each true conflict is accepted or not in each setting (primary convention):

| Model | Both accepted | Agent only | Single-shot only | Neither | McNemar exact p |
|---|---|---|---|---|---|
| GPT-5.4 | 18 | 8 | 5 | 18 | 0.58 |
| Gemini | 31 | 1 | 4 | 13 | 0.38 |

Without presto: GPT 18 / 8 / 4 / 18, p = 0.39; Gemini 31 / 1 / 3 / 13, p = 0.63. (On presto,
Gemini's agent and single-shot resolutions are byte-identical; they were judged differently, see
[Drift](#drift-judge-and-model).)

- Neither model shows a significant difference, and the direction differs between them: the agent
  is accepted on 3 more scenarios than single-shot with GPT, and on 3 fewer with Gemini.
- On these 49 true conflicts the two settings are **comparable**. With n = 49, a difference of a
  few scenarios would not be detected, so this is not evidence that they are equal either.

Two discordant cases show what differs in practice:
- `ansj_seg@2eb46b3c` (GPT, agent only). Single-shot combined left's class with right's variable,
  `AnsjUtils.getInputStream(crfModel)`. The agent grepped the file for `crfModel`, found the field
  that defines it, and wrote the developer's `IOUtil.getInputStream(crfModel)`.
- `apollo@c46f561c` (GPT, single-shot only). Right switched from `Constants` to `ConfigConsts`. The
  agent kept `Constants.DEFAULT_CLUSTER_NAME`; single-shot wrote the developer's
  `ConfigConsts.DEFAULT_CLUSTER_NAME`.

### Drift: judge and model

The three groups were judged in one run by one judge instance, which separates two kinds of drift
from the main comparison.

| Comparison | Result |
|---|---|
| **Judge drift**: June's 132 resolutions re-judged vs the frozen June verdicts | 132/132 verdicts unchanged. The judging was redone: all 132 reasons differ in wording, and 23 scores moved by up to 0.2, but no accept/reject flipped. |
| **Model drift**: single-shot rerun vs June (same code, same model ids) | Gemini: 6 scenarios accepted only in the rerun, 0 only in June, p = 0.031; **without presto 5 vs 0, p = 0.062**. GPT: 2 vs 6, p = 0.29 (the same without presto). |

- **The judge is not perfectly consistent on presto.** Within this one run, the same 2,754-character
  presto resolution was judged four times: accepted at 0.5 and 0.7, rejected at 0.4 and 0.2. The
  reference it is compared with contains unresolved conflict markers (see
  [Limitations](#limitations)). Across all 95 cases where identical text was judged more than
  once, presto is the only one with differing verdicts.
- So one of Gemini's 6 model-drift scenarios is judge noise: June's and the rerun's resolutions are
  byte-identical. Without it, the change is 5 vs 0 and not significant at 0.05. Its direction is
  consistent with the routing to 3.6 Flash, but this run does not establish that the model got
  better.
- GPT's dated model id is unchanged. Its resolutions differ from June's on 14 of 49 true conflicts,
  and its verdicts on 8: run-to-run variation, even at temperature 0.

### (2) structural validity

True conflicts, split by what the check can verify (see [Limitations](#limitations)). Empty
resolutions have no (2) result.

| Group | Single-block files (full check) | Multi-block files (markers only) |
|---|---|---|
| Agent, GPT-5.4 | 32/32 = 100% | 16/16 = 100% |
| Agent, Gemini | 31/32 = 96.9% (presto, a checker false positive) | 15/15 = 100% |
| Single-shot rerun, GPT-5.4 | 31/33 = 93.9% (presto; web3j does not parse) | 16/16 = 100% |
| Single-shot rerun, Gemini | 32/33 = 97.0% (presto) | 16/16 = 100% |
| June, GPT-5.4 | 30/33 = 90.9% (presto; jadx and web3j do not parse) | 16/16 = 100% |
| June, Gemini | 30/31 = 96.8% (presto) | 16/16 = 100% |

Apart from presto, no agent resolution in a single-block file failed (2). The agent ran
`check_java` before every submission, which may be why. The single-shot rerun, though, has only one
genuine failure (web3j), too few to compare the two settings.

### Process and cost

| | Agent, GPT-5.4 | Agent, Gemini | Single-shot, GPT-5.4 | Single-shot, Gemini |
|---|---|---|---|---|
| Model calls per scenario, mean (max) | 4.7 (14) | 10.6 (27) | 1.19 (4) | 1.10 (4) |
| Tool calls: `bash` / `view_file` / `replace_text` / `check_java` | 26 / 293 / 75 / 68 | 256 / 234 / 74 / 81 | — | — |
| Ran `check_java` at least once | 67/67 | 67/67 | the validator runs on every attempt | same |
| Passed `check_java` only after failing it | 0 | 6 | — | — |
| Limits hit | 0 | 1 (presto, tokens) | — | — |
| Tool errors | 8 | 2 | — | — |
| Working time per sample, mean | 11.6 s | 45.2 s | — | — |
| Cost for 67 scenarios | $2.36 | $3.79 | ≈ $0.85, estimate | ≈ $0.20 + thinking, estimate |

- **`check_java` and `submit`.** Gemini's presto sample never submitted (it hit the token limit).
  GPT's presto sample submitted after a failed check.
- **Tool errors.** All 10 are `replace_text` calls whose `old` text matched only with whitespace
  ignored. In every one, the differing lines of `old` carry one extra leading tab. This is most
  likely the tab that separates the line number from the text in `view_file` output, copied along
  with the line. The 6 samples involved all still ended `gradeable`.
- **Agent cost** is logged tokens × list price (input, cached input, output; prices in
  `harness/analyze.py`).
- **Single-shot cost** is not logged: `scripts/run_eval.py` records no token usage.
  `python -m harness.analyze --single-shot RUN.jsonl` estimates it from the prompts the pipeline
  builds, at about 4 characters per token. It counts visible text only. Hidden reasoning or thinking
  tokens are not recorded, so they are not included.
- **The ratio.** For GPT, the agent cost about 3× the single-shot estimate, or less if the
  single-shot run used hidden reasoning tokens. For Gemini, the ratio is unknown: $3.79 against
  $0.20 of visible text plus unrecorded thinking.

### Outcomes

The pre-registered gate held (at most 10% each): not extractable 0/134, out of block 0/134, limits
hit 1/134. The one limit hit (Gemini, presto) still ended `gradeable`, so no sample is
`unfinished`.

The 3 `empty` outcomes:
- **Gemini, `jjwt@3f079803` and `lanproxy@1e0cfe75`.** The target block has an empty side, and
  the model took that side, deleting the block. The developer kept the other side's lines.
  - In both cases the deletion is probably equivalent to the developer's version. jjwt's block lies
    inside a Javadoc comment. lanproxy's block is imports that `import io.netty.channel.*;` and
    `import io.netty.buffer.Unpooled;` earlier in the file already cover.
  - The pre-registered rules still count both as misses (primary) or exclude them (secondary); the
    judge never sees an empty resolution. So the primary rate may undercount Gemini's agent by up to
    2 scenarios. Gemini is not the lower provider, so the headline is unaffected.
- **GPT, `presto@f50b46c7`.** The model first wrote a full resolution. `check_java` then reported a
  duplicate method, which is the checker's false positive (see below). The model deleted the whole
  block. The check failed again with the same message, and the model submitted anyway, saying that
  the file already contained the same methods elsewhere.

### Reproducing the tables

```bash
# agent runs (paid; Docker)
.venv-harness/bin/inspect eval harness/task.py --model openai/gpt-5.4-2026-03-05 \
    --max-samples 6 --log-dir outputs/inspect_logs/full
.venv-harness/bin/inspect eval harness/task.py --model google/gemini-3.5-flash \
    --max-samples 6 --log-dir outputs/inspect_logs/full
.venv-harness/bin/python -m harness.export outputs/inspect_logs/full/*.eval \
    --out outputs/stage3/agent_full.jsonl

# single-shot rerun (paid): the 67 ids of results/solver_eval_20260627_095221.jsonl
.venv/bin/python scripts/run_eval.py --scheme A --no-judge --only-ids <67 ids> \
    --out outputs/eval/runs/eval_A_both_nojudge_stage3_rerun.jsonl

# unified scoring (paid: judge calls)
.venv/bin/python -m evaluation.run_unified_eval --reference june \
    --group agent=outputs/stage3/agent_full.jsonl \
    --group single_shot=outputs/eval/runs/eval_A_both_nojudge_stage3_rerun.jsonl \
    --group june=outputs/eval/eval_A_complete.jsonl \
    --out outputs/deepeval/unified_stage3_full.jsonl

# tables (free)
.venv-harness/bin/python -m harness.report outputs/deepeval/unified_stage3_full.jsonl
.venv-harness/bin/python -m harness.analyze outputs/inspect_logs/full/*.eval
.venv-harness/bin/python -m harness.analyze \
    --single-shot outputs/eval/runs/eval_A_both_nojudge_stage3_rerun.jsonl
```

## Limitations

- **Both settings see only one file.** The agent gets the conflict file and its three versions.
  It has no rest of the repository and no git history. ConflictBench stores only the conflicting
  file (its versions and the merge tools' outputs), and the developer's merge commit is part of the
  repository's history, so giving the history would also take a check for leaks. The result
  is therefore "acting with tools on the same file is comparable to answering once". It does not
  speak to an agent that can search the repository at the two parent commits. In `apollo` above,
  for instance, such an agent could check whether `Constants` still exists on the right side.
- **A setting comparison, not a tool ablation.** See the top of this page.
- **Small n.** 49 true conflicts per model. Only large differences are detectable.
- **Different served model.** Gemini requests were served by `gemini-3.6-flash`. The agent and the
  rerun share it; the June outputs do not.
- **Temperature 0 is not deterministic.** With the same code and model id, GPT's rerun resolutions
  differ from June's on 14 of 49 true conflicts, and the verdicts on 8.
- **The judge is not perfectly consistent** on presto, whose reference contains conflict markers
  (see [Drift](#drift-judge-and-model)).
- **presto@f50b46c7.** The reconstructed target block spans two real conflicts, while ConflictBench
  annotates only the first. The developer region taken from `child` therefore contains the second
  conflict, still unresolved. Separately, the duplicate-declaration check treats
  `insertNullEvery(int, Iterable<?>[])` and `insertNullEvery(int, Iterable<T>)` as duplicates,
  because it ignores array dimensions. These two methods lie outside the block, so no resolution
  of this file can pass (2) or `check_java`, in either setting. In the agent run this led GPT to
  delete the block. The tables give rates without presto; the fix is left for later.
- **(2) on multi-block files** checks markers only. The other blocks keep their markers, so the
  file cannot be parsed.
- **Single-shot cost is an estimate** (see above).
- **Possible contamination.** These are public repositories. The models may have seen the upstream
  merge.
- **The prompt was tuned once on a trial of 10 of the 67 scenarios.** The two added notes are
  generic (the sandbox has only four files; the step budget), but those 10 scenarios are also
  scored.
- **The judge** is the Dataset A judge: precision 100%, recall 64.6% on the five tools'
  resolutions (n = 292). It is strict, so accepted rates are conservative, and its precision on LLM
  resolutions is not measured directly ([RESULTS.md](RESULTS.md)).
