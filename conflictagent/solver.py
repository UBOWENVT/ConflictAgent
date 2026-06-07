"""Solver: build the prompt and call a solver LLM for one conflict.

Clean design (not the old 7-strategy classifier): the model is asked to directly
produce the resolved code for the conflict region — the version a careful developer
would commit — and nothing else. The structured 5-field / 7-strategy scheme from the
old baseline is intentionally dropped.

Input granularity = region only (SPEC #2): the git-merge conflict block plus what each
side changed vs base. No full file in the prompt (the full file is used only locally
for syntax validation; see validate.py).

On a retry, the previous (invalid) attempt and the validator's error are appended so the
model can repair it.
"""
from __future__ import annotations

from . import config, llm
from .data import Scenario

SYSTEM_PROMPT = (
    "You are an expert software engineer resolving a Git merge conflict in a single file.\n"
    "You are given the conflicting region produced by `git merge` — it contains conflict "
    "markers (<<<<<<< / ======= / >>>>>>>, and possibly a diff3 base section between "
    "||||||| and =======) — plus a summary of what each side changed relative to the common "
    "base.\n\n"
    "Produce the correct resolved code that should replace the ENTIRE conflict region: "
    "exactly what a careful developer would commit after understanding both sides' intent.\n\n"
    "Output rules (strict):\n"
    "- Output ONLY the resolved code. No conflict markers.\n"
    "- No explanation, no commentary, no markdown code fences.\n"
)


def _strip_fences(text: str) -> str:
    """Remove a wrapping ```...``` markdown fence if the model added one."""
    t = (text or "").strip()
    if t.startswith("```"):
        lines = t.splitlines()
        lines = lines[1:]                       # drop opening ``` or ```java
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]                  # drop closing ```
        return "\n".join(lines)
    return text


def build_prompt(s: Scenario, prior_attempt: str | None = None,
                 validator_error: str | None = None) -> tuple[str, str]:
    """Return (system, user). On retries, fold in the prior attempt + validator error."""
    parts = [
        "## Conflict region (from `git merge`):",
        s.conflict_chunk,
        "",
        "## What LEFT changed vs base:",
        s.left_diff,
        "",
        "## What RIGHT changed vs base:",
        s.right_diff,
    ]
    if prior_attempt is not None:
        parts += [
            "",
            "## Your previous attempt did NOT pass validation:",
            prior_attempt,
            "",
            "## Validator error:",
            validator_error or "(unspecified)",
            "",
            "Fix the problem and output only the corrected resolved code.",
        ]
    return SYSTEM_PROMPT, "\n".join(parts)


def solve(provider: str, s: Scenario, prior_attempt: str | None = None,
          validator_error: str | None = None) -> dict:
    """Call the solver once; return {'resolution': <code>, 'raw': <raw response>}.

    `resolution` is the model's output with any markdown fence stripped — ready to be
    spliced back into the full file for validation (see validate.py / agent.py).
    """
    system, user = build_prompt(s, prior_attempt, validator_error)
    model = config.SOLVER_MODELS[provider]
    raw = llm.call(provider, model, system, user)
    return {"resolution": _strip_fences(raw).strip(), "raw": raw}
