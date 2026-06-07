"""Solver: build the prompt and call a solver LLM for one conflict.

Clean design (not the old 7-strategy classifier): the model is asked to directly produce
the resolved code for the conflict region — the version a careful developer would commit —
and nothing else.

Input = the reconstructed conflict region from merge.reconstruct_merged() (a diff3 block
showing left / base / right). Region-only (SPEC #2): no full file in the prompt; the full
file is used only locally for syntax validation (validate.py).

On a retry, the previous (invalid) attempt and the validator's error are appended so the
model can repair it.
"""
from __future__ import annotations

from . import config, llm

SYSTEM_PROMPT = (
    "You are an expert software engineer resolving a Git merge conflict in a single file.\n"
    "You are given one conflict region in diff3 form:\n"
    "  <<<<<<< left      our side\n"
    "  ||||||| base      common ancestor\n"
    "  =======           \n"
    "  >>>>>>> right     their side\n\n"
    "Produce the correct resolved code that should replace the ENTIRE conflict region "
    "(from the <<<<<<< line through the >>>>>>> line): exactly what a careful developer would "
    "commit after understanding both sides' intent relative to the base.\n\n"
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


def build_prompt(conflict_region: str, prior_attempt: str | None = None,
                 validator_error: str | None = None) -> tuple[str, str]:
    """Return (system, user). On retries, fold in the prior attempt + validator error."""
    parts = ["## Conflict region:", conflict_region]
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


def solve(provider: str, conflict_region: str, prior_attempt: str | None = None,
          validator_error: str | None = None) -> dict:
    """Call the solver once; return {'resolution': <code>, 'raw': <raw response>}.

    `resolution` is the model's output with any markdown fence stripped — ready to be
    spliced back into the full file for validation (see validate.py / agent.py).
    """
    system, user = build_prompt(conflict_region, prior_attempt, validator_error)
    model = config.SOLVER_MODELS[provider]
    raw = llm.call(provider, model, system, user)
    return {"resolution": _strip_fences(raw).strip(), "raw": raw}
