"""Inference-time validation signals for the agent loop (NO ground truth).

These are the only signals the loop may use to decide whether to retry — they are
all computable without the developer's answer:

  1. syntax_valid(full_file_text) -> (ok: bool, error: str)
       Parse the full file with javalang. Java only (106/180 scenarios). Non-Java
       files (pom.xml, gradle, etc.) need a different check (e.g. XML well-formedness)
       or are excluded from the syntax-valid-rate metric.
  2. has_conflict_markers(text) -> bool
       Detect leftover '<<<<<<<' / '=======' / '>>>>>>>' (and diff3 '|||||||').

To validate, the candidate resolution is spliced back into the FULL file (read
locally from the scenario folder) and then parsed. The full file is needed ONLY
here, never in the LLM prompt.
"""
from __future__ import annotations

import re

_MARKER_RE = re.compile(r"^(<{7}|={7}|>{7}|\|{7})", re.MULTILINE)


def has_conflict_markers(text: str) -> bool:
    """True if any git/diff3 conflict marker line remains."""
    return bool(_MARKER_RE.search(text or ""))


def syntax_valid(full_file_text: str) -> tuple[bool, str]:
    """Parse Java source with javalang; return (ok, error_message).

    TODO: import javalang; try javalang.parse.parse(full_file_text); on
    JavaSyntaxError/LexerError return (False, str(e)); else (True, "").
    """
    raise NotImplementedError


def splice_resolution(full_file_text: str, conflict_chunk: str, resolution: str) -> str:
    """Replace the conflict region in the full file with the candidate resolution,
    so the result can be syntax-checked. TODO: locate the chunk and substitute.
    """
    raise NotImplementedError
