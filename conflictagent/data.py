"""Load ConflictBench scenarios + ground-truth labels.

Primary source = data/ConflictBench.xlsx, sheet 'Paper_Textual_Conflict' (180 rows,
136 true + 44 false conflicts; 106 Java + 74 Non-Java). For region-only input
(SPEC #2) the xlsx CODE SNIPPET columns are sufficient — the full scenario folders
are only needed for LOCAL syntax validation (see validate.py).

Gotchas (verified 2026-06-06):
  - The desirability column is misspelled '{Tool}_Desirability_Same_Developper' (double p).
  - Applicability / desirability labels are 1.0 / 0.0 floats, not strings.
  - Header cells contain newlines, e.g. 'LEFT VERSION\\nCODE SNIPPET'.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from . import config

TOOLS = ["FSTMerge", "JDime", "IntelliMerge", "AutoMerge", "KDIFF3"]

# Column names in the gold sheet (header cells contain literal newlines).
_C_PROJECT = "Project"
_C_COMMIT = "Commit"
_C_FILE = "File Name"
_C_FILETYPE = "File Type"          # 'Java' / 'Non-Java'
_C_VALID = "Valid Conflict"        # 1.0 = genuinely unresolvable (true) conflict
_C_LEFT = "LEFT VERSION\nCODE SNIPPET"
_C_RIGHT = "RIGHT VERSION\nCODE SNIPPET"
_C_MERGED = "MERGED VERSION\nCODE SNIPPET"   # git-merge conflict chunk
_C_CHILD = "CHILD VERSION\nCODE SNIPPET"     # developer resolution (ground truth)


def _tool_columns(tool: str) -> tuple[str, str, str]:
    """(applicability, desirability, code-snippet) column names for a tool.

    NOTE: 'Developper' is misspelled in the source file (double p) — keep it.
    """
    return (
        f"{tool}_Applicability",
        f"{tool}_Desirability_Same_Developper",
        f"{tool}\nCODE SNIPPET",
    )


@dataclass
class Scenario:
    project: str
    commit: str
    file_name: str
    file_type: str               # 'Java' / 'Non-Java'
    valid_conflict: bool | None  # True = genuinely unresolvable conflict
    left_diff: str               # base -> left
    right_diff: str              # base -> right
    conflict_chunk: str          # git-merge conflict region (markers present)
    developer: str               # CHILD = ground-truth resolution

    @property
    def id(self) -> str:
        return f"{self.project}@{self.commit[:8]}"

    @property
    def is_java(self) -> bool:
        return self.file_type == "Java"


@dataclass
class ManualLabel:
    """One human desirability judgment, used to calibrate the LLM judge."""
    project: str
    tool: str
    tool_resolution: str
    developer: str
    desirable: bool              # human: semantically equivalent to developer version


def _s(v) -> str:
    return "" if pd.isna(v) else str(v)


def _b(v) -> bool | None:
    return None if pd.isna(v) else bool(float(v) == 1.0)


def _load_gold_df() -> "pd.DataFrame":
    df = pd.read_excel(config.CONFLICTBENCH_XLSX, sheet_name=config.GOLD_SHEET, header=0)
    return df[df[_C_PROJECT].notna()].copy()


def load_scenarios(java_only: bool = False) -> list[Scenario]:
    """Read the 180 gold scenarios. With java_only=True, keep only the 106 Java ones."""
    df = _load_gold_df()
    out: list[Scenario] = []
    for _, r in df.iterrows():
        s = Scenario(
            _s(r[_C_PROJECT]), _s(r[_C_COMMIT]), _s(r[_C_FILE]), _s(r[_C_FILETYPE]),
            _b(r[_C_VALID]),
            _s(r[_C_LEFT]), _s(r[_C_RIGHT]), _s(r[_C_MERGED]), _s(r[_C_CHILD]),
        )
        if java_only and not s.is_java:
            continue
        out.append(s)
    return out


def load_manual_labels() -> list[ManualLabel]:
    """The ~627 (tool resolution, developer, manual desirability 0/1) triples for judge calibration.

    Only rows where the tool has a 0/1 desirability label are included (NaN skipped).
    """
    df = _load_gold_df()
    out: list[ManualLabel] = []
    for _, r in df.iterrows():
        dev = _s(r[_C_CHILD])
        for tool in TOOLS:
            _, desc_col, snip_col = _tool_columns(tool)
            label = _b(r[desc_col])
            if label is None:
                continue
            out.append(ManualLabel(_s(r[_C_PROJECT]), tool, _s(r[snip_col]), dev, label))
    return out
