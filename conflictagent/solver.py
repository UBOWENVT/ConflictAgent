"""Solver: build the prompt and call a solver LLM for one conflict (SPEC layer B).

The model sees the WHOLE file (so it has full structural context — avoids the brace-straddle
failure of region-only prompts) with every conflict region in diff3 form. Exactly one conflict
is tagged [[RESOLVE THIS CONFLICT]]; the model acts only on that one.

Mirroring the 5 merge tools, the model may either RESOLVE the tagged conflict or declare it a
TRUE_CONFLICT (a punt) needing human reconciliation. The punt is the model's analog of a tool
leaving conflict markers, and feeds the Detection metric; a RESOLVE feeds Desirability.

On a retry, the previous (invalid) attempt and the validator's error are appended.
"""
from __future__ import annotations

from . import config, llm

TARGET_TAG = "[[RESOLVE THIS CONFLICT]]"

SYSTEM_PROMPT = (
    "You are an expert software engineer resolving a Git merge conflict. You are shown the WHOLE "
    "file. It contains one or more conflict regions in diff3 form:\n"
    "  <<<<<<< left      one side's change\n"
    "  ||||||| base      common ancestor\n"
    "  =======\n"
    "  >>>>>>> right     the other side's change\n\n"
    f"Exactly one conflict region is tagged {TARGET_TAG} on its <<<<<<< line. Use the rest of the "
    "file as context, but act ONLY on the tagged conflict.\n\n"
    "First judge whether the tagged conflict is a TRUE conflict: one where the two sides make "
    "genuinely incompatible changes that require human judgment to reconcile, so no single "
    "automatic resolution is clearly correct. Otherwise it is resolvable.\n\n"
    "Respond in EXACTLY one of these two forms, with the verdict on the first line:\n\n"
    "VERDICT: RESOLVE\n"
    "<the resolved code that replaces the ENTIRE tagged region — from its <<<<<<< line through "
    "its >>>>>>> line. Output ONLY that code: no conflict markers, no fences, no commentary.>\n\n"
    "or\n\n"
    "VERDICT: TRUE_CONFLICT\n"
    "(output nothing after this line)"
)


def _strip_fences(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        lines = t.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines)
    return text


def _parse(raw: str) -> tuple[str, str]:
    """Return (verdict, resolution). verdict in {'resolve','true_conflict','unparsed'}."""
    text = raw or ""
    lines = text.splitlines()
    verdict = "unparsed"
    body_start = 0
    for i, line in enumerate(lines):
        lu = line.upper()
        if "VERDICT" in lu and ("RESOLVE" in lu or "TRUE_CONFLICT" in lu or "TRUE CONFLICT" in lu):
            verdict = "true_conflict" if ("TRUE_CONFLICT" in lu or "TRUE CONFLICT" in lu) else "resolve"
            body_start = i + 1
            break
    if verdict == "unparsed":
        # No explicit verdict line: if it clearly punted, treat as true_conflict; else treat whole
        # output as a resolution attempt.
        up = text.upper()
        if "TRUE_CONFLICT" in up or "TRUE CONFLICT" in up:
            return "true_conflict", ""
        return "resolve", _strip_fences(text).strip()
    if verdict == "true_conflict":
        return "true_conflict", ""
    return "resolve", _strip_fences("\n".join(lines[body_start:])).strip()


def build_prompt(marked_file: str, prior_attempt: str | None = None,
                 validator_error: str | None = None) -> tuple[str, str]:
    """Return (system, user). On retries, fold in the prior attempt + validator error."""
    parts = ["## File (resolve only the tagged conflict):", marked_file]
    if prior_attempt is not None:
        parts += [
            "",
            "## Your previous attempt did NOT pass validation:",
            prior_attempt,
            "",
            "## Validator error:",
            validator_error or "(unspecified)",
            "",
            "Fix the problem. Output the verdict line then only the corrected resolved code.",
        ]
    return SYSTEM_PROMPT, "\n".join(parts)


def solve(provider: str, marked_file: str, prior_attempt: str | None = None,
          validator_error: str | None = None) -> dict:
    """Call the solver once. Return {'verdict','resolution','raw'}.

    verdict: 'resolve' (resolution is the target block's resolved code), 'true_conflict' (punt,
    resolution=''), or 'unparsed' is normalized away by _parse.
    """
    system, user = build_prompt(marked_file, prior_attempt, validator_error)
    model = config.SOLVER_MODELS[provider]
    raw = llm.call(provider, model, system, user)
    verdict, resolution = _parse(raw)
    return {"verdict": verdict, "resolution": resolution, "raw": raw}
