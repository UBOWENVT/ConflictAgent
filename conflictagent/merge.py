"""Reconstruct the git-merge conflict for a scenario from its base/left/right files.

Uses `git merge-file` (git plumbing; no repo needed). It produces the full file with
conflict markers exactly as a developer sees after `git merge`. This is the SINGLE source
of both:
  (a) the conflict region shown to the solver (validate.extract_conflict_region), and
  (b) the full-file scaffold for syntax validation (validate.splice_resolution + syntax_valid).

Keeping both from one source means solve and validate stay consistent.
"""
from __future__ import annotations

import os
import subprocess
import tempfile


def reconstruct_merged(base: str, left: str, right: str) -> tuple[str, bool]:
    """Return (merged_text_with_markers, had_conflict).

    Runs:  git merge-file -p <left> <base> <right>   (left = ours, right = theirs)
    git merge-file exits 0 for a clean merge and with the number of remaining conflicts
    otherwise, so had_conflict = (returncode != 0).
    """
    with tempfile.TemporaryDirectory() as d:
        p_left = os.path.join(d, "left")
        p_base = os.path.join(d, "base")
        p_right = os.path.join(d, "right")
        for path, text in ((p_left, left), (p_base, base), (p_right, right)):
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        proc = subprocess.run(
            ["git", "merge-file", "-p",
             "-L", "left", "-L", "base", "-L", "right",
             p_left, p_base, p_right],
            capture_output=True,
            text=True,
        )
    return proc.stdout, (proc.returncode != 0)
