"""Inference-time validation signals for the agent loop (NO ground truth).

All functions here are computable without the developer's answer — they are the only
signals the loop may use to decide whether to retry:

  - has_conflict_markers(text)      -> leftover <<<<<<< / ======= / >>>>>>> (and diff3 |||||||)
  - extract_conflict_region(merged) -> the first <<<<<<< ... >>>>>>> block (solver input)
  - splice_resolution(merged, res)  -> put the candidate back where the conflict was
  - syntax_valid(java_text)         -> (ok, error) via javalang  [Java only]
  - has_duplicate_declarations(java_text) -> over-scoped/duplicated decls javalang misses [Java]

The full merged file (with markers) comes from merge.reconstruct_merged(); splicing the
candidate into it and parsing gives the syntax-valid signal. Tested on real ConflictBench
scenarios 2026-06-06.
"""
from __future__ import annotations

import re

# A line beginning with a 7-char conflict marker.
_MARKER_LINE = re.compile(r"^(<{7}|={7}|>{7}|\|{7})", re.MULTILINE)

# A whole conflict block from '<<<<<<<' through the next '>>>>>>>' line (DOTALL).
_CONFLICT_BLOCK = re.compile(r"^<{7}.*?^>{7}.*?$", re.DOTALL | re.MULTILINE)


def has_conflict_markers(text: str) -> bool:
    """True if any git/diff3 conflict marker line remains."""
    return bool(_MARKER_LINE.search(text or ""))


def extract_conflict_region(merged: str) -> str | None:
    """Return the first conflict block (the region shown to the solver), or None."""
    m = _CONFLICT_BLOCK.search(merged or "")
    return m.group(0) if m else None


def conflict_blocks(merged: str) -> list[str]:
    """Return all conflict blocks. MVP targets single-block scenarios; len != 1 is flagged
    by the agent (multi-block would need per-block resolutions)."""
    return _CONFLICT_BLOCK.findall(merged or "")


def splice_resolution(merged: str, resolution: str, count: int = 0) -> str:
    """Replace conflict block(s) in `merged` with `resolution`.

    count=0 replaces all blocks; count=1 replaces only the first. (Most scenarios have
    a single block; multi-block files would need per-block resolutions — a later concern.)
    """
    return _CONFLICT_BLOCK.sub(lambda _m: resolution, merged, count=count)


def block_spans(merged: str) -> list[tuple[int, int]]:
    """(start, end) character spans of every conflict block, in order."""
    return [(m.start(), m.end()) for m in _CONFLICT_BLOCK.finditer(merged or "")]


def splice_block(merged: str, resolution: str, block_index: int) -> str:
    """Replace ONLY the conflict block at `block_index` with `resolution`; leave the rest
    of the file (including any other conflict blocks) untouched."""
    spans = block_spans(merged)
    if not (0 <= block_index < len(spans)):
        return merged
    s, e = spans[block_index]
    return merged[:s] + resolution + merged[e:]


def split_diff3_block(block: str) -> tuple[str, str, str]:
    """Split one diff3 conflict block into (left, base, right) code, markers stripped.

    Expects the `git merge-file --diff3` shape:
        <<<<<<< left
        <left lines>
        ||||||| base
        <base lines>
        =======
        <right lines>
        >>>>>>> right
    A non-diff3 block (no ||||||| section) yields base=''. Used to build the trivial
    pick-left / pick-right / pick-longer / union baselines in evaluation.
    """
    left: list[str] = []
    base: list[str] = []
    right: list[str] = []
    section = None  # 'left' | 'base' | 'right'
    for l in (block or "").splitlines():
        if l.startswith("<<<<<<<"):
            section = "left"
        elif l.startswith("|||||||"):
            section = "base"
        elif l.startswith("======="):
            section = "right"
        elif l.startswith(">>>>>>>"):
            section = None
        elif section == "left":
            left.append(l)
        elif section == "base":
            base.append(l)
        elif section == "right":
            right.append(l)
    return "\n".join(left), "\n".join(base), "\n".join(right)


def syntax_valid(java_text: str) -> tuple[bool, str]:
    """Parse Java source with javalang. Return (ok, error_message).

    javalang's exceptions often have an empty str(); we surface `.description` and the
    failing token (`.at`) so the retry feedback to the solver is actually informative.
    """
    import javalang  # lazy

    try:
        javalang.parse.parse(java_text)
        return True, ""
    except Exception as e:  # JavaSyntaxError, LexerError, etc.
        desc = getattr(e, "description", None) or str(e) or type(e).__name__
        at = getattr(e, "at", None)
        loc = f" (at {at})" if at else ""
        return False, f"{desc}{loc}"


def has_duplicate_declarations(java_text: str) -> tuple[bool, str]:
    """Detect declarations duplicated by an OVER-SCOPED resolution. Return (has_dup, message).

    The solver sometimes emits code from outside the tagged conflict region — e.g. when the
    block boundary falls mid-construct, it 'completes' a class/method it was only shown as
    context. Splicing that back duplicates a type or method that still exists elsewhere in the
    file: a COMPILE error that javalang's syntax parse does NOT flag (so syntax_valid passes).
    This closes that gap. Non-parseable input -> (False, '') because syntax_valid is the gate
    for syntax; overloads (same name, different parameter types) are NOT duplicates.
    """
    import javalang  # lazy

    try:
        tree = javalang.parse.parse(java_text)
    except Exception:
        return False, ""

    _TYPES = ("ClassDeclaration", "InterfaceDeclaration", "EnumDeclaration", "AnnotationDeclaration")
    _METHODS = ("MethodDeclaration", "ConstructorDeclaration")

    def _sig(member) -> tuple:
        return (member.name,
                tuple((getattr(p.type, "name", None), getattr(p, "varargs", False))
                      for p in (member.parameters or [])))

    def _walk(type_decl, path: str) -> str | None:
        seen_types: set[str] = set()
        seen_methods: set[tuple] = set()
        for m in getattr(type_decl, "body", None) or []:
            kind = type(m).__name__
            if kind in _TYPES:
                if m.name in seen_types:
                    return f"duplicate nested type {path}.{m.name}"
                seen_types.add(m.name)
                sub = _walk(m, f"{path}.{m.name}")
                if sub:
                    return sub
            elif kind in _METHODS:
                sig = _sig(m)
                if sig in seen_methods:
                    return f"duplicate method {path}.{m.name}"
                seen_methods.add(sig)
        return None

    top: set[str] = set()
    for td in tree.types or []:
        if td.name in top:
            return True, f"duplicate top-level type {td.name}"
        top.add(td.name)
        msg = _walk(td, td.name)
        if msg:
            return True, msg
    return False, ""
