"""check_java: the agent's self-check, run INSIDE the sandbox (no repository code there).

    python3 check_java.py <file> [--expect-blocks N]

Same pass/fail semantics as the single-shot pipeline's inference-time validator
(conflictagent.agent._validate), applied to the edited file instead of a spliced resolution:

  - the tagged conflict must be gone: no [[RESOLVE THIS CONFLICT]] tag, no stray marker lines,
    and every remaining conflict region well-formed;
  - no conflict regions left (single-block file): the whole file must parse with javalang and
    have no duplicate declarations;
  - other regions left (multi-block file): pass when exactly N well-formed regions remain
    (N = --expect-blocks = original blocks - 1); their markers are expected. As a reference
    signal only (never a pass condition), the file is also parsed with every remaining region
    replaced by its left side.

One known difference: _validate also rejects an empty resolution. This check sees only the
edited file, so a deleted target region passes if the rest of the file is valid.

validate.py next to this script is a byte-identical copy of conflictagent/validate.py (enforced by
tests/harness/test_check_java.py), so both sides use the same marker regex and javalang checks.
Exit status: 0 = pass, 1 = fail, 2 = usage / read error.
"""
from __future__ import annotations

import argparse
import re
import sys

import validate

TARGET_TAG = "[[RESOLVE THIS CONFLICT]]"
_MARKER = re.compile(r"^(<{7}|\|{7}|={7}|>{7})")
_WELL_FORMED = (["<<<<<<<", "|||||||", "=======", ">>>>>>>"], ["<<<<<<<", "=======", ">>>>>>>"])


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _structure_problem(text: str) -> str | None:
    """A description of the first marker problem, or None if every marker line belongs to a
    well-formed diff3/merge region."""
    spans = validate.block_spans(text)
    for s, e in spans:
        kinds = [m.group(1) for line in text[s:e].split("\n") if (m := _MARKER.match(line))]
        if kinds not in _WELL_FORMED:
            return f"malformed conflict region starting at line {_line_of(text, s)}"
    offset = 0
    for line in text.split("\n"):
        if _MARKER.match(line) and not any(s <= offset < e for s, e in spans):
            return f"stray conflict marker at line {_line_of(text, offset)}: {line[:40]!r}"
        offset += len(line) + 1
    return None


def _left_side_reference(text: str) -> str:
    """Parse result with every remaining conflict region replaced by its left side."""
    spans = validate.block_spans(text)
    for s, e in reversed(spans):
        left, _, _ = validate.split_diff3_block(text[s:e])
        text = text[:s] + left + text[e:]
    ok, err = validate.syntax_valid(text)
    return "parses" if ok else f"does not parse ({err})"


def check(text: str, expect_blocks: int | None = None) -> tuple[bool, str]:
    """(passed, message) for the edited conflict file."""
    if TARGET_TAG in text:
        line = _line_of(text, text.index(TARGET_TAG))
        return False, (f"FAIL: the tagged conflict is not resolved yet: its <<<<<<< line with "
                       f"{TARGET_TAG} is still at line {line}. Replace the whole region, from that "
                       f"line through its >>>>>>> line.")
    problem = _structure_problem(text)
    if problem:
        return False, (f"FAIL: {problem}. Conflict markers are left over from the tagged region; "
                       f"remove all of its markers (<<<<<<<, |||||||, =======, >>>>>>>).")
    remaining = len(validate.conflict_blocks(text))
    if expect_blocks is not None and remaining != expect_blocks:
        if remaining > expect_blocks:
            hint = "the tagged region probably still has its conflict markers"
        else:
            hint = ("other conflict regions were resolved or removed; resolve ONLY the tagged one "
                    "and leave the others exactly as they were")
        return False, (f"FAIL: expected {expect_blocks} untouched conflict region(s) to remain, "
                       f"found {remaining}: {hint}.")
    if remaining:
        return True, (f"PASS: the tagged conflict is resolved. {remaining} other conflict region(s) "
                      f"remain; that is expected, leave them as they are. (Reference only, not a "
                      f"pass condition: with the other regions taken as their left side, the file "
                      f"{_left_side_reference(text)}.)")
    ok, err = validate.syntax_valid(text)
    if not ok:
        return False, f"FAIL: the file does not parse as Java: {err}"
    dup, what = validate.has_duplicate_declarations(text)
    if dup:
        return False, (f"FAIL: {what}. The resolution probably includes code from outside the "
                       f"conflict region; replace only the region itself.")
    return True, "PASS: no conflict markers remain and the file parses as Java."


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("path")
    ap.add_argument("--expect-blocks", type=int, default=None)
    args = ap.parse_args()
    try:
        with open(args.path, "rb") as f:
            text = f.read().decode("utf-8", errors="replace")
    except OSError as e:
        print(f"ERROR: cannot read {args.path}: {e.strerror}")
        return 2
    ok, message = check(text, args.expect_blocks)
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
