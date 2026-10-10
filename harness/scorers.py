"""Deterministic scoring of the agent's final file (no LLM judge here).

What is scored is the conflict file left in the sandbox, not the submit() text.

1. Extraction. The original file is prefix + target block + suffix (Sample.metadata).
     exact            final == prefix + R + suffix                       -> R is the resolution
     whitespace_only  equal outside the block once whitespace inside each line and trailing
                      blank lines are ignored (e.g. tabs expanded, CRLF, final newline)
                                                                         -> R taken line-aligned
     out_of_block     the file changed outside the target block; R is located by aligning the
                      unchanged lines around it (used only by the secondary convention)
     not_extractable  no conflict file, or the block cannot be located
2. Outcome, per the rules fixed before the first real run (OUTCOME_RULES; docs to follow).
3. (2) structural validity, exactly as Dataset B computes it: splice the cleaned resolution back
   into the ORIGINAL conflict file; multi-block files whose other blocks still carry markers fall
   back to the marker-only check.

The (1) developer-match verdict is NOT computed here: the judge runs afterwards, offline, over the
exported resolutions (one judge instance shared with the single-shot reruns and the June outputs).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from difflib import SequenceMatcher

from inspect_ai.scorer import Score, Target, mean, scorer
from inspect_ai.solver import TaskState
from inspect_ai.util import sandbox

from conflictagent import validate

# outcome -> (primary convention, secondary convention). Fixed denominators per model:
# 49 true / 18 false. "judge" = the region goes to the (1) judge; "miss" = counted as not
# accepted without a judge call; "exclude" = dropped from the secondary denominator.
OUTCOME_RULES: dict[str, tuple[str, str]] = {
    "gradeable": ("judge", "judge"),
    "empty": ("miss", "exclude"),
    "no_edit": ("miss", "exclude"),
    "unfinished": ("miss", "exclude"),     # stopped (limit) with the target still unresolved
    "markers": ("miss", "miss"),           # submitted with conflict markers in the resolution
    "out_of_block": ("miss", "judge"),     # secondary judges the in-block region only
    "not_extractable": ("miss", "exclude"),
}


@dataclass(frozen=True)
class Extraction:
    status: str            # exact | whitespace_only | out_of_block | not_extractable
    region: str | None     # final-file text standing where the target block was


def _norm(line: str) -> str:
    return " ".join(line.split())


def _content_lines(text: str) -> list[str]:
    """Lines with trailing blank lines dropped (so a missing or extra final newline is ignored)."""
    lines = text.split("\n")
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def _split_around(prefix: str, suffix: str) -> tuple[list[str], list[str]] | None:
    """Whole lines before and after the block (a block always spans whole lines)."""
    if prefix and not prefix.endswith("\n"):
        return None
    if suffix and not suffix.startswith("\n"):
        return None
    before = prefix.split("\n")[:-1] if prefix else []
    after = _content_lines(suffix[1:]) if suffix else []
    return before, after


def _line_aligned_region(final: str, prefix: str, suffix: str) -> str | None:
    around = _split_around(prefix, suffix)
    if around is None:
        return None
    before, after = around
    fin = _content_lines(final)
    p, r = len(before), len(after)
    if len(fin) < p + r:
        return None
    if [_norm(l) for l in fin[:p]] != [_norm(l) for l in before]:
        return None
    if r and [_norm(l) for l in fin[len(fin) - r:]] != [_norm(l) for l in after]:
        return None
    return "\n".join(fin[p:len(fin) - r])


def _diff_aligned_region(final: str, prefix: str, suffix: str,
                         min_matched: float = 0.5) -> str | None:
    """Locate the block in a file that also changed elsewhere: align the lines around the block
    with the final file; the region is what sits between the last matched line before the block
    and the first matched line after it."""
    around = _split_around(prefix, suffix)
    if around is None:
        return None
    before, after = around
    fin = _content_lines(final)
    a = [_norm(l) for l in before + after]
    if not a:
        return final
    matched: dict[int, int] = {}
    for m in SequenceMatcher(None, a, [_norm(l) for l in fin], autojunk=False).get_matching_blocks():
        for k in range(m.size):
            matched[m.a + k] = m.b + k
    if len(matched) < min_matched * len(a):
        return None
    p = len(before)
    pre = [matched[i] for i in range(p) if i in matched]
    post = [matched[i] for i in range(p, len(a)) if i in matched]
    lo = pre[-1] + 1 if pre else 0
    hi = post[0] if post else len(fin)
    return "\n".join(fin[lo:hi]) if lo <= hi else None


def extract_region(final: str | None, prefix: str, suffix: str) -> Extraction:
    if final is None:
        return Extraction("not_extractable", None)
    if (len(final) >= len(prefix) + len(suffix)
            and final.startswith(prefix) and final.endswith(suffix)):
        return Extraction("exact", final[len(prefix):len(final) - len(suffix)])
    # block deleted together with its line break: the newline ending the prefix and the one
    # starting the suffix collapse into one
    if suffix.startswith("\n") and (prefix == "" or prefix.endswith("\n")) \
            and final == prefix + suffix[1:]:
        return Extraction("exact", "")
    if suffix == "" and prefix.endswith("\n") and final == prefix[:-1]:
        return Extraction("exact", "")
    region = _line_aligned_region(final, prefix, suffix)
    if region is not None:
        return Extraction("whitespace_only", region)
    region = _diff_aligned_region(final, prefix, suffix)
    if region is not None:
        return Extraction("out_of_block", region)
    return Extraction("not_extractable", None)


def clean_region(region: str) -> str:
    """Same trimming as the single-shot pipeline applies to a resolution (solver._clean_resolution
    without the fence stripping): surrounding blank lines and trailing whitespace."""
    return region.strip("\n").rstrip()


def structural_validity(resolution: str, prefix: str, suffix: str) -> tuple[bool, str]:
    """(2), the same checks and verdicts as evaluation.metrics.StructuralValidity over
    evaluation.dataset.build_solver_testcases' splice (that module needs deepeval, which this
    environment does not install; tests/harness/test_scorers.py replays the June verdicts)."""
    if validate.has_conflict_markers(resolution):
        return False, "leftover conflict markers in resolution"
    spliced = prefix + resolution + suffix
    if validate.has_conflict_markers(spliced):
        return True, "no markers in resolution (other conflict blocks remain: marker-only check)"
    ok, err = validate.syntax_valid(spliced)
    if not ok:
        return False, f"java does not parse: {err}"
    dup, msg = validate.has_duplicate_declarations(spliced)
    if dup:
        return False, f"over-scoped duplicate declaration: {msg}"
    return True, "no markers; parses; no duplicate declarations"


def classify_outcome(ext: Extraction, unchanged: bool, submitted: bool) -> str:
    if ext.status in ("not_extractable", "out_of_block"):
        return ext.status
    if unchanged:
        return "no_edit"
    if not ext.region.strip():
        return "empty"
    if validate.has_conflict_markers(ext.region):
        return "markers" if submitted else "unfinished"
    return "gradeable"


def _submitted(state: TaskState) -> bool:
    return any(getattr(m, "tool_calls", None) and any(tc.function == "submit" for tc in m.tool_calls)
               for m in state.messages)


@scorer(metrics={"gradeable": [mean()], "structurally_valid": [mean()]})
def conflict_file_scorer():
    async def score(state: TaskState, target: Target) -> Score:
        m = state.metadata
        prefix, suffix = m["prefix"], m["suffix"]
        try:
            final = (await sandbox().read_file(m["conflict_path"], text=False)).decode(
                "utf-8", errors="replace")
        except (FileNotFoundError, IsADirectoryError, PermissionError):
            final = None
        ext = extract_region(final, prefix, suffix)
        unchanged = (ext.status == "exact" and hashlib.sha256(
            ext.region.encode("utf-8")).hexdigest() == m["target_block_sha256"])
        submitted = _submitted(state)
        outcome = classify_outcome(ext, unchanged, submitted)

        resolution = clean_region(ext.region) if ext.region is not None else None
        valid, valid_reason = (structural_validity(resolution, prefix, suffix)
                               if resolution else (None, "no resolution to check"))
        final_markers = validate.has_conflict_markers(final) if final is not None else None
        final_parses = (validate.syntax_valid(final)[0]
                        if final is not None and not final_markers else None)
        return Score(
            value={"gradeable": int(outcome == "gradeable"),
                   "structurally_valid": int(valid is True)},
            answer=resolution,
            explanation=outcome,
            metadata={
                "outcome": outcome,
                "extraction": ext.status,
                "region": ext.region,
                "structurally_valid": valid,
                "structural_reason": valid_reason,
                "submitted": submitted,
                "final_has_markers": final_markers,
                "final_parses": final_parses,
            },
        )

    return score
