"""Solver: build the prompt and call a solver LLM for one conflict (SPEC layer B).

The model sees a WINDOW of the file — the file skeleton (package + imports + the type
declaration line) plus the minimal complete brace scope enclosing the target conflict — not
the whole file. Whole-file context blew up on big files (RxJava's Observable.java alone was
~103k tokens); the window keeps full structural context around the conflict while eliding
unrelated code. Files at/under config.WINDOW_FULLFILE_MAX_LINES are shown whole. Every conflict
region is in diff3 form; exactly one is tagged [[RESOLVE THIS CONFLICT]] and the model acts only
on that one. The window is purely what is SHOWN to the model — validation and splicing in agent.py
always operate on the full reconstructed file, so windowing cannot corrupt the resolution.

Two prompt schemes (config.SCHEMES), an ablation run at full scale:
  A  no validity gating: always reason -> resolve -> self-report strategy + confidence. Detection
     becomes confidence calibration. (primary)
  B  classic two-stage: declare TRUE_CONFLICT (punt, no resolution) or RESOLVABLE then resolve.

The model self-reports STRATEGY (which side[s] it kept: L/R/M and combinations, matching
ConflictBench's Child Resolution Pattern vocabulary) and CONFIDENCE (low/medium/high). The prompt
never mentions the developer and never reveals any ground-truth label.

On a retry, the previous (invalid) attempt and the validator's error are appended.
"""
from __future__ import annotations

import re

from . import config, llm

TARGET_TAG = "[[RESOLVE THIS CONFLICT]]"

_MARK_START = "<<<<<<<"
_MARK_BASE = "|||||||"
_MARK_SEP = "======="
_MARK_END = ">>>>>>>"

_INTRO = (
    "You are an expert software engineer resolving a Git merge conflict. You are shown the "
    "relevant section of a file (unrelated parts may be elided and marked "
    "\"... <N lines omitted> ...\"). It contains one or more conflict regions in diff3 form:\n"
    "  <<<<<<< left      one side's change\n"
    "  ||||||| base      common ancestor\n"
    "  =======\n"
    "  >>>>>>> right     the other side's change\n\n"
    f"Exactly one conflict region is tagged {TARGET_TAG} on its <<<<<<< line. Use the rest of the "
    "section as context, but resolve ONLY the tagged conflict.\n\n"
)

_STRATEGY_DOC = (
    "STRATEGY: one of L, R, L+R, M, L+M, R+M, L+R+M — which side(s) your resolution keeps. "
    "L=left side only, R=right side only, M=new or modified code not taken verbatim from either "
    "side. Combine with + when the resolution mixes them.\n"
)

_RESOLUTION_DOC = (
    "RESOLUTION:\n<the resolved code that replaces the ENTIRE tagged region — from its <<<<<<< "
    "line through its >>>>>>> line. Output only that code: no conflict markers, no fences, no "
    "commentary.>"
)

SYSTEM_A = (
    _INTRO +
    "Think about what each side changed relative to the base, then produce the single resolution "
    "a careful engineer would commit. Report which side(s) it draws from and how confident you are.\n\n"
    "Respond with EXACTLY these fields, in this order, and nothing else:\n\n"
    "REASONING: <one or two sentences on what each side changed and why your resolution is right>\n"
    + _STRATEGY_DOC +
    "CONFIDENCE: <low, medium, or high>\n"
    + _RESOLUTION_DOC
)

SYSTEM_B = (
    _INTRO +
    "First decide whether the tagged conflict is a TRUE conflict: the two sides make genuinely "
    "incompatible changes that require human judgment, so no single automatic resolution is "
    "clearly correct. Otherwise it is RESOLVABLE.\n\n"
    "If it is a TRUE conflict, respond with EXACTLY:\n\n"
    "CONFLICT_TYPE: TRUE_CONFLICT\n"
    "REASONING: <one or two sentences on why the two sides are irreconcilable>\n"
    "(output nothing after this)\n\n"
    "If it is RESOLVABLE, respond with EXACTLY these fields, in this order, and nothing else:\n\n"
    "CONFLICT_TYPE: RESOLVABLE\n"
    "REASONING: <one or two sentences on what each side changed and why your resolution is right>\n"
    + _STRATEGY_DOC +
    "CONFIDENCE: <low, medium, or high>\n"
    + _RESOLUTION_DOC
)


# --------------------------------------------------------------------------- #
# Context window
# --------------------------------------------------------------------------- #

def _is_marker(line: str) -> bool:
    return line.startswith((_MARK_START, _MARK_BASE, _MARK_SEP, _MARK_END))


def _structural_view(lines: list[str]) -> list[str]:
    """Per-line code used for brace counting: only lines OUTSIDE any conflict block survive.

    Conflict-internal lines (all three sides) and marker lines are blanked, so the brace count
    reflects the file's structural skeleton — the enclosing method/class braces, which sit outside
    the conflict. This avoids the diff3 block's three-versions-at-once brace imbalance.
    """
    view: list[str] = []
    inside = False
    for l in lines:
        if l.startswith(_MARK_START):
            inside = True
            view.append("")
        elif l.startswith(_MARK_END):
            inside = False
            view.append("")
        elif _is_marker(l):
            view.append("")
        else:
            view.append("" if inside else l)
    return view


def _first_type_open(view: list[str]) -> int | None:
    """Line index of the opening '{' of the first top-level type (class/interface/enum/record).

    Find the type-declaration keyword first, then the next '{' from there — this skips annotation
    braces (e.g. @SuppressWarnings({...})) that appear before the class line.
    """
    kw = re.compile(r"\b(class|interface|enum|record)\b")
    t = next((i for i, code in enumerate(view) if kw.search(code)), None)
    for i in range(t if t is not None else 0, len(view)):
        if "{" in view[i]:
            return i
    return None


def _enclosing_scope(view: list[str], tb_start: int, tb_end: int,
                     header_end: int, n: int) -> tuple[int, int]:
    """(open_line, close_line) of the innermost brace scope enclosing the target block."""
    stack: list[int] = []
    for i in range(tb_start):
        for ch in view[i]:
            if ch == "{":
                stack.append(i)
            elif ch == "}":
                if stack:
                    stack.pop()
    scope_open = stack[-1] if stack else header_end

    depth = 0
    opened = False
    scope_close = n - 1
    for i in range(scope_open, n):
        for ch in view[i]:
            if ch == "{":
                depth += 1
                opened = True
            elif ch == "}":
                depth -= 1
        if opened and depth <= 0:
            scope_close = i
            break

    # Guarantee the target block is fully covered even if brace counting is imperfect.
    return min(scope_open, tb_start), max(scope_close, tb_end)


def _merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    rs = sorted(ranges)
    merged = [list(rs[0])]
    for a, b in rs[1:]:
        if a <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged]


def _elide(k: int) -> str:
    return f"// ... <{k} lines omitted> ..."


def _assemble(lines: list[str], ranges: list[tuple[int, int]], n: int) -> str:
    out: list[str] = []
    prev_end = -1
    for a, b in ranges:
        if a > prev_end + 1:
            out.append(_elide(a - (prev_end + 1)))
        out.extend(lines[a:b + 1])
        prev_end = b
    if prev_end < n - 1:
        out.append(_elide(n - 1 - prev_end))
    return "\n".join(out)


def build_window(marked_file: str, target_idx: int, max_full_lines: int | None = None) -> str:
    """Return the windowed view shown to the solver (skeleton + enclosing scope of the target).

    Falls back to the whole file when: the file is small, the target block can't be located
    safely, or no top-level type structure is found. The full target conflict block (markers +
    tag) is always preserved verbatim.
    """
    max_full = config.WINDOW_FULLFILE_MAX_LINES if max_full_lines is None else max_full_lines
    lines = marked_file.splitlines()
    n = len(lines)
    if n <= max_full:
        return marked_file

    starts = [i for i, l in enumerate(lines) if l.startswith(_MARK_START)]
    ends = [i for i, l in enumerate(lines) if l.startswith(_MARK_END)]
    if not (0 <= target_idx < len(starts)) or len(starts) != len(ends):
        return marked_file
    tb_start, tb_end = starts[target_idx], ends[target_idx]

    view = _structural_view(lines)
    header_end = _first_type_open(view)
    if header_end is None:
        return marked_file

    if tb_start <= header_end:
        ranges = [(0, max(header_end, tb_end))]
    else:
        scope_open, scope_close = _enclosing_scope(view, tb_start, tb_end, header_end, n)
        ranges = [(0, header_end), (scope_open, scope_close)]
    return _assemble(lines, _merge_ranges(ranges), n)


# --------------------------------------------------------------------------- #
# Output parsing
# --------------------------------------------------------------------------- #

def _strip_fences(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        body = t.splitlines()[1:]
        if body and body[-1].strip() == "```":
            body = body[:-1]
        return "\n".join(body)
    return text


def _clean_resolution(s: str) -> str:
    """Strip code fences and surrounding blank lines / trailing whitespace, but PRESERVE the
    leading indentation of the code (it replaces the whole conflict block in place)."""
    return _strip_fences(s).strip("\n").rstrip()


def _canon_strategy(raw: str) -> str:
    """Normalize a free-form strategy answer to canonical L/R/M components (config order)."""
    up = (raw or "").upper()
    comps = []
    if re.search(r"\bL\b", up) or "LEFT" in up:
        comps.append("L")
    if re.search(r"\bR\b", up) or "RIGHT" in up:
        comps.append("R")
    if re.search(r"\bM\b", up) or "MERGE" in up or "MIXED" in up or "NEW" in up:
        comps.append("M")
    order = {c: i for i, c in enumerate(config.STRATEGY_COMPONENT_ORDER)}
    return "+".join(sorted(set(comps), key=lambda c: order.get(c, 9)))


def _canon_confidence(raw: str) -> str:
    low = (raw or "").lower()
    if "high" in low:
        return "high"
    if "low" in low:
        return "low"
    if "med" in low:
        return "medium"
    return ""


def _parse(raw: str, scheme: str) -> dict:
    """Parse the structured solver output.

    Returns {'conflict_type','reasoning','strategy','confidence','resolution'}.
    conflict_type in {'resolvable','true_conflict'}; resolution is '' for a punt.
    """
    text = raw or ""
    lines = text.splitlines()
    out = {"conflict_type": None, "reasoning": "", "strategy": "", "confidence": "", "resolution": ""}
    res_idx = None
    for i, line in enumerate(lines):
        lu = line.strip().upper()
        if lu.startswith("CONFLICT_TYPE") or lu.startswith("CONFLICT TYPE"):
            val = line.split(":", 1)[-1].upper()
            if "TRUE_CONFLICT" in val or "TRUE CONFLICT" in val:
                out["conflict_type"] = "true_conflict"
            elif "RESOLV" in val:
                out["conflict_type"] = "resolvable"
        elif lu.startswith("REASONING"):
            out["reasoning"] = line.split(":", 1)[-1].strip()
        elif lu.startswith("STRATEGY"):
            out["strategy"] = _canon_strategy(line.split(":", 1)[-1])
        elif lu.startswith("CONFIDENCE"):
            out["confidence"] = _canon_confidence(line.split(":", 1)[-1])
        elif lu.startswith("RESOLUTION"):
            res_idx = i
            break

    if res_idx is not None:
        inline = lines[res_idx].split(":", 1)[-1].strip()
        body = "\n".join(lines[res_idx + 1:])
        body = (inline + "\n" + body) if inline and body else (inline or body)
        out["resolution"] = _clean_resolution(body)

    if scheme == "A":
        out["conflict_type"] = "resolvable"

    if out["conflict_type"] == "true_conflict":
        out["resolution"] = ""
    elif res_idx is None:
        # Model ignored the format. In B, an explicit punt phrase still counts as a punt;
        # otherwise treat the whole output as the resolution body.
        up = text.upper()
        if scheme == "B" and ("TRUE_CONFLICT" in up or "TRUE CONFLICT" in up):
            out["conflict_type"] = "true_conflict"
        else:
            out["conflict_type"] = out["conflict_type"] or "resolvable"
            out["resolution"] = _clean_resolution(text)
    return out


# --------------------------------------------------------------------------- #
# Prompt + call
# --------------------------------------------------------------------------- #

def build_prompt(scheme: str, windowed_file: str, prior_attempt: str | None = None,
                 validator_error: str | None = None) -> tuple[str, str]:
    """Return (system, user). On retries, fold in the prior attempt + validator error."""
    system = SYSTEM_A if scheme == "A" else SYSTEM_B
    parts = ["## File section (resolve only the tagged conflict):", windowed_file]
    if prior_attempt is not None:
        parts += [
            "",
            "## Your previous attempt did NOT pass validation:",
            prior_attempt,
            "",
            "## Validator error:",
            validator_error or "(unspecified)",
            "",
            "Fix the problem. Re-output all the fields; put the corrected code under RESOLUTION.",
        ]
    return system, "\n".join(parts)


def solve(provider: str, scheme: str, windowed_file: str, prior_attempt: str | None = None,
          validator_error: str | None = None) -> dict:
    """Call the solver once. Return the parsed fields plus 'raw'."""
    system, user = build_prompt(scheme, windowed_file, prior_attempt, validator_error)
    model = config.SOLVER_MODELS[provider]
    raw = llm.call(provider, model, system, user)
    out = _parse(raw, scheme)
    out["raw"] = raw
    return out
