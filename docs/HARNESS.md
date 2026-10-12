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

> Status: one full scored run, 2026-10-10. Results, the failure analysis and the limitations are
> at the end of this page.

## One scenario, end to end

`junit4@4c8d3ff5`, the smallest file in the population, as it went through the full run. Each step
names the section below that defines it.

**0. The conflict.** `src/main/java/junit/runner/Version.java` (18 lines) returns JUnit's version
string. Both sides changed the same line:

| Version | The line | Meaning |
|---|---|---|
| base | `return "4.10-SNAPSHOT";` | 4.10 in development |
| left | `return "4.11-SNAPSHOT";` | development moves on to 4.11 |
| right | `return "4.10";` | the 4.10 release |
| developer (`child`) | `return "4.11-SNAPSHOT";` | kept left |

ConflictBench labels it a true conflict.

**1. The conflict file** ([Samples](#samples)). `git merge-file --diff3` on base, left and right
gives a 24-line file with one conflict block. The block's first line is tagged:

```java
	public static String id() {
<<<<<<< left   [[RESOLVE THIS CONFLICT]]
		return "4.11-SNAPSHOT";
||||||| base
		return "4.10-SNAPSHOT";
=======
		return "4.10";
>>>>>>> right
	}
```

**2a. Single-shot.**
- The file is under 400 lines, so the prompt shows it whole.
- Each model answered in one call with `return "4.11-SNAPSHOT";`.
- The pipeline spliced the answer into the file and validated it: no markers, parses, no duplicate
  declarations. No retry was needed.

**2b. Agent** ([Sandbox](#sandbox), [Agent and tools](#agent-and-tools)). In a fresh container with no
network, the workspace holds the tagged file and `sides/{base,left,right}/<path>`, nothing else (the
image adds Python, javalang and the checker). GPT-5.4 took 4
model calls:
1. `view_file` on all four files, in one call;
2. `replace_text`: lines 12–18 (the whole block) → `return "4.11-SNAPSHOT";`;
3. `check_java` → `PASS: no conflict markers remain and the file parses as Java.`;
4. `submit`: "Resolved the tagged conflict by keeping the updated snapshot version string …".

Gemini took 7 calls. It opened only the conflict file, ran `ls -la` and `find . -type f`, made the
same replacement, viewed the file again, ran `check_java` and submitted. The cost was $0.018 (GPT-5.4, 8.3 s) and $0.024 (Gemini, 25.7 s).

**3. Extracting the resolution** ([Scoring rules](#scoring-rules)). The final file is the original
prefix, one new line, and the original suffix, byte for byte. So the extraction is `exact`, the
outcome is `gradeable`, and the resolution is `return "4.11-SNAPSHOT";`.

**4. The reference.** Offline, the developer's resolution of the same block is cut from `child`,
located by the unchanged lines just before and after the block. The model never sees `child`.

**5. (1) developer-match.**
- The judge gets the conflict block, the resolution and the developer's resolution.
- All six resolutions of this scenario scored 1.0 and were accepted: agent, single-shot rerun and
  June, for each of the two models.
- The judge's reason: "The Actual Output exactly matches the Expected Output, returning
  '4.11-SNAPSHOT' which corresponds to the left side of the conflict. …"

**6. (2) structural validity.** The file with the resolution spliced in has no markers, parses, and
has no duplicate declarations.

Everything in [Results](#results-full-run-2026-10-10) is this, repeated for 67 scenarios × 2 models
in each setting. In this scenario both settings got it right; the agent took 4 and 7 model calls
where single-shot took 1.

## Layout

```text
harness/
  task.py          Inspect task: dataset + agent + tools + sandbox + scorer + limits
  dataset.py       the fixed 67 Dataset B scenarios -> Inspect Samples
  tools.py         view_file / replace_text / check_java, and the pre-agent workspace step
  scorers.py       deterministic scoring of the final file (no LLM judge)
  prompts.py       agent instructions
  export.py        Inspect logs -> run_eval.py-schema JSONL for the offline judge
  analyze.py       per-sample process metrics, process signals and token cost
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
| Not root | Runs as uid 1000 (`agent`). The checker in `/opt/harness` is root-owned, so the model cannot change it, but it can read it (one sample did; see [Failure analysis](#failure-analysis)). |
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
- **Multi-block file:** pass if exactly *original − 1* well-formed regions remain; their markers are
  expected. As an informational signal (never a pass condition), it also reports whether the file
  parses with the remaining regions replaced by their left side.

One difference: `_validate` rejects an empty resolution, while `check_java` sees only the edited
file. Scoring treats an empty resolution as described below.

**Limits:** 60 messages, 10 minutes, 600,000 tokens per sample. Temperature 0. Reasoning effort is
left at each provider's default. `fail_on_error=0.05`; interrupted runs continue with
`inspect eval-retry`.

These were set after a first trial (10 scenarios × 2 models) with 40 messages and 400,000 tokens.
The message limit cut off 3 of the 10 Gemini samples, which spent many steps looking for
repository files and git that the sandbox does not have. Two short notes were then added to the
prompt: that the four files are all there is (no repository, no git), and the step budget. The
message and token limits were raised to the values above. Both changes are generic (environment facts and limits),
not tied to any scenario. A second trial on the same 10 scenarios then checked the changes. Trial
runs are for debugging only and do not feed any reported number.

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

If other blocks still carry markers, only the marker check applies (see [Limitations](#limitations)).

### 5. Process metrics

From the logs (`harness/analyze.py`):
- model calls, and tool calls per tool;
- tool errors, including argument-parsing errors, and truncated tool outputs;
- whether `check_java` ran before `submit`, and whether a failed check was later fixed;
- limits hit;
- tokens (input, cached, output, reasoning) and time;
- for the failure analysis, yes/no process signals (`--signals`): whether the agent searched the
  files, probed the environment, ran `check_java` before its first edit, or read the checker's
  source.

Cost is tokens × list price, computed afterwards.

## Results (full run, 2026-10-10)

Every number below comes from the run outputs, through the commands in
[Reproducing the tables](#reproducing-the-tables). The per-sample verdicts and process metrics are
frozen in `results/stage3_*`. These files hold no conflict files and no full resolutions; the
judge's reasons and the failure labels' notes quote short fragments. `python
scripts/verify_numbers.py` recomputes the figures listed in it from these files, with no API key.
The other figures (for example the tool-error details, the presto judgments and the end-to-end
example) need the Inspect logs and resolutions, which stay local (gitignored).

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
| **Model drift**: single-shot rerun vs June (same code, same model ids) | Gemini: 6 scenarios accepted only in the rerun, 0 only in June, p = 0.031; **without presto 5 vs 0, p = 0.063**. GPT: 2 vs 6, p = 0.29 (the same without presto). |

- **The judge is not perfectly consistent on presto.** Within this one run, the same 2,754-character
  presto resolution was judged four times: accepted at 0.5 and 0.7, rejected at 0.4 and 0.2. The
  reference it is compared with contains unresolved conflict markers (see
  [Limitations](#limitations)). Across all 95 cases where identical text was judged more than
  once, presto is the only one with differing verdicts.
- So one of Gemini's 6 model-drift scenarios is judge noise: June's and the rerun's resolutions are
  byte-identical. Without it, the change is 5 vs 0 and not significant at 0.05. Its direction is
  consistent with the routing to 3.6 Flash, but this run does not establish that the model got
  better. Two of the 6 (`jedis@b013a74c`, `jjwt@3f079803`) are scenarios where June's Gemini
  returned an empty resolution.
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

### Failure analysis

**Scope.** Two sets of misses, under the primary convention:
- all 52 agent samples that missed (GPT-5.4 28, Gemini 24);
- the 10 (scenario, model) pairs that only the single-shot rerun missed.

**Method.**
- Each miss got a card: the target block, the developer region, the resolution, the judge's reason
  and the agent's steps.
- The classes were formed after reading all the cards. The plan's checklist of guessed failure
  modes served only as a cross-check.

**Codebook.** The classes describe how a resolution differs from the developer's. They do not say
which of the two is right: the developer's resolution is one acceptable answer, not the only one.

- A *change* is what one side did relative to base: a line added, removed or edited. Differences
  in whitespace and comments alone do not count.
- **E** is the evaluation side: the resolution is equivalent to the developer's, or cannot be
  compared with it.
- **M** is a real difference in code. It may be the model's mistake, or the developer's choice.

Precedence runs from top to bottom; the first class that applies is the label. M6, which only
single-shot can produce, is checked before the other M classes: when the output reaches beyond the
block, its content cannot be compared line for line.

| Code | Class | Rule |
|---|---|---|
| E3 | No matchable reference | No resolution built from the three versions could match the developer region: it still contains conflict markers, or it holds a value that none of the versions has and none can supply (such as a timestamp generated at merge time). A reference that is only redundant (say, a duplicate import), or that joins the two sides' code, or adds an import that a side's wildcard already covers, is not E3. |
| E2 | Deleted, not judged | The resolution is empty. Empty resolutions are not judged and count as misses (pre-registered). |
| E1 | Equivalent, judged wrong | The difference is only in comments or whitespace, or the same classes end up imported (a wildcard covers them, or the file imports them outside the block). |
| M6 | Over-scoped output | Single-shot only: the returned resolution includes code from outside the block. The agent edits the block in place, so this cannot happen in the agent setting. |
| M1 | Took a different whole version | Each side differs from base, ignoring whitespace and comments. The developer region equals one version (left, right or base) and the resolution another, again ignoring whitespace and comments. |
| M5 | Order only | Same statements, in a different order. |
| M4 | Rewrote | The resolution has code that none of the three versions has anywhere in the file: new types, calls or statements. Joining two edits of a line that both sides changed, and the glue such a join needs (say, a `return` when one side's new body meets the other side's new return type), does not count. Carrying one side's change into code that only the other side added does. |
| M3 | Lost a change | A change the developer kept is missing. |
| M2 | Kept both sides; the developer kept one | The resolution has everything the developer region has, plus a change the developer dropped, usually the other side's. Mostly the textbook three-way merge of two changes that do not overlap. |

**Labels of the 52 agent misses.**

| Class | GPT-5.4 | Gemini | Total |
|---|---|---|---|
| E3 No matchable reference | 2 | 2 | 4 |
| E2 Deleted, not judged | 0 | 2 | 2 |
| E1 Equivalent, judged wrong | 6 | 2 | 8 |
| M1 Took a different whole version | 5 | 4 | 9 |
| M5 Order only | 1 | 1 | 2 |
| M4 Rewrote | 1 | 1 | 2 |
| M3 Lost a change | 3 | 1 | 4 |
| M2 Kept both sides; the developer kept one | 10 | 11 | 21 |
| **Total** | **28** | **24** | **52** |

**Findings.**

- **14 of the 52 misses are on the evaluation side.**
  - E1 (8). In 7 of them, the judge rejected a difference that its own evaluation step 4 says to
    disregard: comments, whitespace, or an import set that is visibly equivalent within the block.
    In the eighth (`lanproxy@1e0cfe75`, GPT), the import the judge found missing is already
    imported outside the block, and the judge sees only the block (see [Limitations](#limitations)).
  - Single-shot missed all 8 of these scenarios as well, so they do not bias the comparison. They
    make the absolute rates conservative. The rates are not adjusted, as pre-registered.
  - E3 (4): presto in both models (markers in the reference), and `openapi-generator@bade71c6` in
    both, where the developer's line carries a generated timestamp that is later than both sides'.
  - E2 (2): the two Gemini deletions described under [Outcomes](#outcomes).
- **M2 is the largest class: 21 of the 52.**
  - 10 of the 21 are blocks of imports only, and M2 covers 9 of the 12 misses on false conflicts.
  - A typical case is `JustAuth@3199334d`, a false conflict. Left adds an import; right moves
    another class to a new package, on a different line. Both models kept both changes; the
    developer kept left only.
  - Why the developer dropped one side is not in this file, so neither setting can know it. This is
    where the one-file limitation shows most.
- **M1 (9)** are choices between two plausible versions that nothing in the file decides, often a
  one-line setting or modifier such as Matisse's MIME type or caffeine's `protected`.
- **Rewrites, losses and reorderings are few:** M3 4, M4 2, M5 2.
  - In `jedis@b013a74c` (M4, GPT-5.4), right deleted `disconnect()` and gave the class a new
    parent. The agent kept the method but rewrote 4 of its 6 lines for the new parent. The developer
    kept left's version unchanged. (Gemini's agent was accepted here.)
  - In `HikariCP@68a52f14` (M5), the resolution has the same statements as the developer's. The
    developer had moved one side's block ahead of the other's.
- **Misses unique to one setting** (all 67 scenarios):
  - Missed only by the single-shot rerun (10): M3 7, M1 2, M6 1. The lost changes are small edits
    on one side, such as graphhopper's `"CAR"` → `"car"`.
  - Missed only by the agent (9): 3 on the evaluation side, then M2 3, M1 1, M3 1, M4 1.
  - So the agent lost fewer small changes and more often kept both sides. This is a direction only:
    the class counts were not tested, and the paired accept/reject comparison above is not
    significant.
- **Process signals against outcome.** Each model has one signal that varies (all 67 scenarios
  per model, primary convention):

  | Signal | Accepted with the signal | Accepted without it | Fisher exact p |
  |---|---|---|---|
  | GPT-5.4 searched the files (`grep` or `diff`): 18 of 67 | 13/18 = 72% | 26/49 = 53% | 0.18 |
  | Gemini probed the environment (`find`, `ls`, `git`, `stat`, `which`, `pwd`, `tree`, `env`, `diff -r`, `cat /…`, `/opt`, `/etc`): 20 of 67 | 11/20 = 55% | 32/47 = 68% | 0.40 |

  - Neither difference is significant.
  - The other signals barely vary. Gemini searched in 66 of 67 samples; GPT probed in none.
  - The prompt says that the sandbox holds only the four files and no git. Gemini probed anyway,
    and it ran `check_java` before its first edit in 6 samples.
  - Every sample ran `check_java` at least once, and no sample submitted without having run it,
    so that signal has nothing to cross.
- **One sample read the checker's source.** Gemini on presto had been stopped by the checker's
  false positive. It searched the whole container with `find /`, then read
  `/opt/harness/check_java.py` and its `validate.py`.
  - The checker holds no answers, and scoring happens outside the container.
  - Still, the harness could run the checker as a different user, so that the model cannot read it.
- **Checklist items with no evidence** were left out of the codebook: edits outside the block
  (0/134), submitting without a self-check (0/134), and acting after reading only part of a large
  file (not observed).

**Agreement.** The labels were assigned from the cards by Claude Code, the coding agent used to
build this harness. The repository author independently labeled 15 misses in two rounds. They were drawn with
`random.Random(20261010).sample` from the 52 misses sorted by (model, scenario), before any
discussion; `verify_numbers.py` checks that the draw reproduces. All figures are raw agreement on the author's first labels; with n = 15,
no kappa is reported.

- **Round 1** (items 1–8, first codebook): 3/8.
  - On what the model and the developer had done, the two descriptions agreed on 7 of 8. The eighth
    card had cut off the end of the developer region.
  - The disagreements were about definitions, which were then revised:
    - M classes describe a difference, not a model error;
    - base counts as a version in M1;
    - a redundant reference is not E3;
    - E1 was renamed, with both of its causes stated.
- **Round 2** (items 9–15, revised codebook): 4/7.
  - Four of the 15 items had appeared as examples in the first codebook. On the four round-2 items
    whose labels the author had not seen, agreement was 3/4.
  - The remaining disagreements were about counting changes relative to base, which the codebook
    now states explicitly.
- **Overall:** 7/15 on first labels. After the discussion, the author agreed with the final label
  on all 15.
- **After the revision**, only the M1 rule was re-applied to all labels, by script: 2 labels changed
  from M2 to M1. The other revisions changed wording only.

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

# frozen copies in results/ (free), then the check
cp outputs/deepeval/unified_stage3_full.jsonl results/stage3_unified_eval_20261010_163404.jsonl
.venv-harness/bin/python -m harness.analyze outputs/inspect_logs/full/*.eval \
    --csv results/stage3_agent_metrics_20261010.csv
.venv-harness/bin/python -m harness.analyze \
    --single-shot outputs/eval/runs/eval_A_both_nojudge_stage3_rerun.jsonl \
    --csv results/stage3_single_shot_20261010.csv
.venv-harness/bin/python -m harness.analyze outputs/inspect_logs/full/*.eval --signals \
    --csv results/stage3_process_signals_20261012.csv
python scripts/verify_numbers.py
```

The failure labels in `results/stage3_failure_labels_20261012.csv` were assigned by Claude Code
from the cards (see [Failure analysis](#failure-analysis)); no script regenerates them.
`verify_numbers.py` checks that they cover exactly the agent misses and the single-shot-only misses
of the frozen scoring file, and recomputes the counts and the agreement from them.

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
- **One reference resolution.** The developer's resolution is one acceptable answer, not the only
  one. It is sometimes redundant (in lanproxy the developer's file imports `Unpooled` twice), and
  it often reflects a choice that the file alone does not explain (M2 in the
  [failure analysis](#failure-analysis)).
- **The judge sees only the conflict block**, not the file around it. It cannot credit an import
  that the file already has outside the block (1 of the 8 E1 cases). Showing it the file's imports
  would mean re-judging every group; this is left for later.
- **Empty resolutions are not judged.** Deleting the block can be a valid resolution (2 cases here,
  both probably equivalent), but the pre-registered rule counts it as a miss.
- **The failure labels come from one annotator**, an LLM coding agent, checked by the author on 15
  random cases (raw agreement 7/15; see [Agreement](#failure-analysis)). The annotator and the
  judge are both Claude models, and the cards showed the judge's reason, so the labels may lean
  toward the judge's reading. The author saw the same cards, so the spot check offsets this only in
  part.
- **(2) on multi-block files** checks markers only. The other blocks keep their markers, so the
  file cannot be parsed.
- **Single-shot cost is an estimate** (see above).
- **Possible contamination.** These are public repositories. The models may have seen the upstream
  merge.
- **The prompt and limits were tuned once on a trial of 10 of the 67 scenarios**, then checked by a
  second trial on the same 10. The two added notes are generic (the sandbox has only four files;
  the step budget), but those 10 scenarios are also scored.
- **The judge** is the Dataset A judge: precision 100%, recall 64.6% on the five tools'
  resolutions (n = 292). It is strict, so accepted rates are conservative, and its precision on LLM
  resolutions is not measured directly ([RESULTS.md](RESULTS.md)).
