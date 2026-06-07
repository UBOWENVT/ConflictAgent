# ConflictAgent

An LLM **coding agent** that resolves Java merge conflicts with a *validate-and-repair* loop,
evaluated on the [ConflictBench](https://github.com/UBOWENVT/ConflictBench) benchmark (180 real
3-way merge scenarios).

> **Status: in progress.** Scaffolding stage — no experimental results yet. This README will be
> updated with measured numbers once the pipeline runs. (No placeholder metrics on purpose.)

## Motivation

ConflictBench includes a baseline experiment where a single LLM call ("single-shot") tries to
classify and resolve each conflict. A known failure mode of that baseline is **syntactically
invalid / hallucinated code** in the generated resolution. ConflictAgent targets exactly that:
it wraps the LLM in a loop that *validates* each candidate resolution and *repairs* it using the
validator's feedback, instead of trusting one shot.

## How it works

Two layers are kept strictly separate:

**Agent loop (no ground truth — inference-time signals only)**
1. A solver LLM generates a candidate resolution for the conflict region.
2. The candidate is spliced back into the full file and validated: Java syntax (via `javalang`)
   + a check for leftover conflict markers (`<<<<<<<` / `=======` / `>>>>>>>`).
3. If invalid, the concrete error is fed back and the solver retries (up to a retry cap).
4. Once valid, the resolution is finalized.

**Evaluation (uses ground truth — runs *outside* the loop)**
5. An offline LLM-as-judge (a *different* model from the solver) compares the finalized
   resolution against the developer's actual resolution for semantic equivalence.

The loop never sees the developer's answer — using it inside the loop would be data leakage.

## Metrics (reported per retry round)

- **syntax-valid rate** — fraction of resolutions that parse (Java subset).
- **token-level F1** vs the developer version (cheap lexical overlap, no judge needed).
- **judge semantic-equivalence** vs the developer version (judge calibrated against ConflictBench's
  manual labels first).

The headline result is the **delta between the single-shot baseline and the agent loop**.

## Models

- Solvers: an OpenAI GPT-5.x model + a Google Gemini 3.x model.
- Judge: an Anthropic Claude model (different vendor from both solvers, to avoid self-preference).

Configure model IDs and keys in `conflictagent/config.py` and `.env` (see `.env.example`).

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then fill in your API keys
python scripts/fetch_data.py   # pulls ConflictBench data into ./data (gitignored)
```

## Layout

```
conflictagent/      core package
  config.py         models, paths, retry cap, input-granularity knob
  llm.py            thin multi-provider chat wrapper
  data.py           load ConflictBench scenarios + ground-truth labels
  solver.py         build prompt + call solver LLM
  validate.py       javalang syntax check + conflict-marker check
  agent.py          the validate-and-repair loop
  judge.py          offline LLM-as-judge
  metrics.py        the three metrics
scripts/            entry points: fetch_data / run_baseline / run_agent / calibrate_judge
data/               ConflictBench data (gitignored; populated by fetch_data.py)
```

## Credits

Built on ConflictBench (Shen & Meng, *JSS* 214, 2024).
