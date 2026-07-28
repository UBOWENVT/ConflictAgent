# ConflictAgent — full prompt reference (solver)

This file = everything actually sent to the solver LLM (OpenAI / Gemini), verbatim.
Source: `conflictagent/solver.py` — `SYSTEM_A` / `SYSTEM_B` + `build_prompt()` + `build_window()`.
The judge is separate: it now runs as GEval (DeepEval), with criteria taken from `judge.py`'s
JUDGE_SYSTEM rubric and carried by ① ResolutionAcceptability in `evaluation/metrics.py` — out of
scope for this file.

Two changes since the 2026-06-08 redirect:

1. **Context = a window** (no longer the whole file): the file skeleton (package + import block + class
   declaration line) + the smallest complete brace scope enclosing the target block; if the file is
   small (≤ `config.WINDOW_FULLFILE_MAX_LINES`, currently 400 lines) the whole file is still sent. The
   window is only **what the model sees**; validation and splicing always run on the full reconstructed
   file, so the window can never contaminate the resolution.
2. **Two schemes (A primary, B ablation)**, with a structured `FIELD:` output contract for easy
   parsing:
   - **A**: no conflict-type gating, always produces a resolution + self-reported strategy + confidence.
     Detection becomes confidence calibration.
   - **B**: classic two-stage — first decides `TRUE_CONFLICT` (punt, no resolution) or `RESOLVABLE`
     (then resolves). punt vs the human `Valid Conflict` label = the Detection metric, comparable to
     the 5 tools under the same convention.

---

## 1. SYSTEM PROMPT — Scheme A (verbatim)

```text
You are an expert software engineer resolving a Git merge conflict. You are shown the relevant section of a file (unrelated parts may be elided and marked "... <N lines omitted> ..."). It contains one or more conflict regions in diff3 form:
  <<<<<<< left      one side's change
  ||||||| base      common ancestor
  =======
  >>>>>>> right     the other side's change

Exactly one conflict region is tagged [[RESOLVE THIS CONFLICT]] on its <<<<<<< line. Use the rest of the section as context, but resolve ONLY the tagged conflict.

Think about what each side changed relative to the base, then produce the single resolution a careful engineer would commit. Report which side(s) it draws from and how confident you are.

Respond with EXACTLY these fields, in this order, and nothing else:

REASONING: <one or two sentences on what each side changed and why your resolution is right>
STRATEGY: one of L, R, L+R, M, L+M, R+M, L+R+M — which side(s) your resolution keeps. L=left side only, R=right side only, M=new or modified code not taken verbatim from either side. Combine with + when the resolution mixes them.
CONFIDENCE: <low, medium, or high>
RESOLUTION:
<the resolved code that replaces the ENTIRE tagged region — from its <<<<<<< line through its >>>>>>> line. Output only that code: no conflict markers, no fences, no commentary.>
```

---

## 2. SYSTEM PROMPT — Scheme B (verbatim)

Same opening as A; the difference is it first asks the model to classify `CONFLICT_TYPE`, and to punt
(no resolution) on a true conflict.

```text
You are an expert software engineer resolving a Git merge conflict. You are shown the relevant section of a file (unrelated parts may be elided and marked "... <N lines omitted> ..."). It contains one or more conflict regions in diff3 form:
  <<<<<<< left      one side's change
  ||||||| base      common ancestor
  =======
  >>>>>>> right     the other side's change

Exactly one conflict region is tagged [[RESOLVE THIS CONFLICT]] on its <<<<<<< line. Use the rest of the section as context, but resolve ONLY the tagged conflict.

First decide whether the tagged conflict is a TRUE conflict: the two sides make genuinely incompatible changes that require human judgment, so no single automatic resolution is clearly correct. Otherwise it is RESOLVABLE.

If it is a TRUE conflict, respond with EXACTLY:

CONFLICT_TYPE: TRUE_CONFLICT
REASONING: <one or two sentences on why the two sides are irreconcilable>
(output nothing after this)

If it is RESOLVABLE, respond with EXACTLY these fields, in this order, and nothing else:

CONFLICT_TYPE: RESOLVABLE
REASONING: <one or two sentences on what each side changed and why your resolution is right>
STRATEGY: one of L, R, L+R, M, L+M, R+M, L+R+M — which side(s) your resolution keeps. L=left side only, R=right side only, M=new or modified code not taken verbatim from either side. Combine with + when the resolution mixes them.
CONFIDENCE: <low, medium, or high>
RESOLUTION:
<the resolved code that replaces the ENTIRE tagged region — from its <<<<<<< line through its >>>>>>> line. Output only that code: no conflict markers, no fences, no commentary.>
```

---

## 3. USER MESSAGE — first round (no retry)

Structure = one header line + the window (the target block's `<<<<<<<` line has `   [[RESOLVE THIS
CONFLICT]]` appended). The user message is identical across both schemes; only the system differs.

```text
## File section (resolve only the tagged conflict):
{window: skeleton + elision markers + the scope enclosing the target block, target block tagged}
```

---

## 4. USER MESSAGE — retry round (when validation fails)

Same window, followed by the previous failed resolution + the validator error + a fix instruction. At
most `MAX_RETRIES` retries.

```text
## File section (resolve only the tagged conflict):
{same window as above}

## Your previous attempt did NOT pass validation:
{the model's previous resolution}

## Validator error:
{the validator's error, e.g. "Output still contained conflict markers (<<<<<<< / ======= / >>>>>>>)."}

Fix the problem. Re-output all the fields; put the corrected code under RESOLUTION.
```

---

## 5. What a window looks like (real output)

Below is a 496-line class (a conflict inside one of its methods), after `build_window`, exactly as it
enters the user slot (produced by a sandbox run):

```text
package com.example.app;

import java.util.List;
import java.util.Map;

public class Demo {
// ... <240 lines omitted> ...
    public int compute(int x) {
<<<<<<< left   [[RESOLVE THIS CONFLICT]]
        return x * 2;
||||||| base
        return x;
=======
        return x * 3;
>>>>>>> right
    }
// ... <241 lines omitted> ...
```

Key points: package / imports / class declaration are kept, the method scope enclosing the target
block is kept, the target conflict block is kept intact (all three sides + markers), and the other
methods collapse to elision markers. 496 lines compress to 17.
Small files (≤ 400 lines) are not collapsed — the whole file is sent.

---

## 6. Expected model output & parsing

### Scheme A (always resolves)

```text
REASONING: Right multiplies by 3, a superset of left's intent; base just returned x.
STRATEGY: R
CONFIDENCE: high
RESOLUTION:
        return x * 3;
```

### Scheme B — resolvable

```text
CONFLICT_TYPE: RESOLVABLE
REASONING: ...
STRATEGY: R
CONFIDENCE: high
RESOLUTION:
        return x * 3;
```

### Scheme B — judged a true conflict (punt)

```text
CONFLICT_TYPE: TRUE_CONFLICT
REASONING: Both sides redesign the same API incompatibly.
```

### Parsing (`_parse(raw, scheme)`)

- Grab `CONFLICT_TYPE` / `REASONING` / `STRATEGY` / `CONFIDENCE` by `FIELD:` prefix; everything after
  `RESOLUTION:` (multi-line) = the resolution.
- The `RESOLUTION` body has markdown fences stripped and leading/trailing blank lines/whitespace
  trimmed, but **leading indentation is preserved** (the resolution replaces the whole conflict region,
  so indentation matters).
- `STRATEGY` is normalized to an `L/R/M` combination (sorted L→R→M, recognizing left/right/merge
  synonyms).
- `CONFIDENCE` is normalized to `low/medium/high`; left blank if unrecognized.
- Scheme A has no `CONFLICT_TYPE`, so it is always treated as `resolvable`.
- Fallback: in B, if the model breaks format but says `TRUE_CONFLICT` → treat as punt; otherwise treat
  the whole body as the resolution.

Returned fields: `{conflict_type, reasoning, strategy, confidence, resolution}` (plus `raw`).

---

## 7. How the two vendors wire the same system+user into their SDK

The text is identical; only the mechanical wiring differs (see `llm.py`):

- **OpenAI**: `messages=[{role:"system", content:SYSTEM}, {role:"user", content:USER}]`
- **Gemini**: `contents=USER`, `config=GenerateContentConfig(system_instruction=SYSTEM)`
- **Anthropic** (judge only): `system=SYSTEM, messages=[{role:"user", content:USER}]`

**temperature**: defaults to `config.LLM_TEMPERATURE = 0` (reproducible evaluation), routed by
`llm.call` to each vendor's correct slot. Note some OpenAI models only accept the default temperature
and error on 0 — if an OpenAI call fails on temperature during smoke testing, set
`config.LLM_TEMPERATURE` to `None` (which omits the parameter entirely).
