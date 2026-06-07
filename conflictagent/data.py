"""Load ConflictBench scenarios + ground-truth labels.

Primary source = data/ConflictBench.xlsx, sheet 'Paper_Textual_Conflict' (180 rows,
136 true + 44 false conflicts; 106 Java + 74 Non-Java). For region-only input
(SPEC #2) the xlsx CODE SNIPPET columns are sufficient — the full scenario folders
are only needed for LOCAL syntax validation (see validate.py).

Gotchas (verified 2026-06-06):
  - The desirability column is misspelled '{Tool}_Desirability_Same_Developper' (double p).
  - Applicability / desirability labels are 1.0 / 0.0 floats, not strings.
  - Header cells contain newlines, e.g. 'LEFT VERSION\\nCODE SNIPPET'.

Relevant columns:
  Project, Commit, File Name, File Type ('Java' / 'Non-Java'), Valid Conflict (1/0),
  'LEFT VERSION\\nCODE SNIPPET'   -> base->left diff
  'RIGHT VERSION\\nCODE SNIPPET'  -> base->right diff
  'MERGED VERSION\\nCODE SNIPPET' -> git-merge conflict chunk
  'CHILD VERSION\\nCODE SNIPPET'  -> developer resolution (ground truth)
  per tool: '{Tool}_Applicability', '{Tool}_Desirability_Same_Developper', '{Tool}\\nCODE SNIPPET'
"""
from __future__ import annotations

from dataclasses import dataclass

TOOLS = ["FSTMerge", "JDime", "IntelliMerge", "AutoMerge", "KDIFF3"]


@dataclass
class Scenario:
    project: str
    commit: str
    file_type: str          # 'Java' / 'Non-Java'
    valid_conflict: bool    # True = genuinely unresolvable conflict
    left_diff: str
    right_diff: str
    conflict_chunk: str     # git-merge conflict region (markers present)
    developer: str          # CHILD = ground-truth resolution


def load_scenarios(java_only: bool = False) -> list[Scenario]:
    """Read the gold sheet into Scenario objects.

    TODO: pandas.read_excel(CONFLICTBENCH_XLSX, sheet_name=GOLD_SHEET); filter Project notna;
    optionally keep only File Type == 'Java'.
    """
    raise NotImplementedError


def load_manual_labels() -> "object":
    """Return the ~627 (tool resolution, developer, manual desirability 0/1) triples
    used to calibrate the judge. TODO: build from the per-tool columns.
    """
    raise NotImplementedError
