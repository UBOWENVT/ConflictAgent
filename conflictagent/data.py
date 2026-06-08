"""Load ConflictBench scenarios + ground-truth labels.

Primary source = data/ConflictBench.xlsx, sheet 'Paper_Textual_Conflict' (180 rows,
136 true + 44 false conflicts; 106 Java + 74 Non-Java).

Resolved files live under data/scenarios/{project}__{commit}/{ver} once fetched
(scripts/fetch_data.py): base/left/right/child plus each merge tool's output folder
(FSTMerge/IntelliMerge/AutoMerge/JDime/KDiff3) where present. These feed
merge.reconstruct_merged(), validate.syntax_valid(), and groundtruth.resolution_region().

The xlsx now serves mainly as the LABEL source (desirability) + a fallback/oracle: the CODE
SNIPPET cells are annotations — version snippets (LEFT/RIGHT/CHILD) are unified diffs, tool
snippets are clean code. Prefer the real files; fall back to cleaned xlsx snippets.

Gotchas (verified 2026-06):
  - Desirability column misspelled '{Tool}_Desirability_Same_Developper' (double p).
  - Applicability / desirability labels are 1.0 / 0.0 floats.
  - Header cells contain newlines, e.g. 'LEFT VERSION\\nCODE SNIPPET'.
  - xlsx tool name 'KDIFF3' maps to repo folder 'KDiff3' (see _TOOL_FOLDER).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from . import config

TOOLS = ["FSTMerge", "JDime", "IntelliMerge", "AutoMerge", "KDIFF3"]  # xlsx column names

# xlsx tool name -> repo folder name (only KDIFF3 differs in casing)
_TOOL_FOLDER = {"KDIFF3": "KDiff3"}

# All resolved-file folders that may exist per scenario (folder names, not xlsx names).
_RESOLVED_VERS = ("base", "left", "right", "child",
                  "FSTMerge", "IntelliMerge", "AutoMerge", "JDime", "KDiff3")

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


def tool_folder(tool: str) -> str:
    """Map an xlsx tool name to its repo/data folder name."""
    return _TOOL_FOLDER.get(tool, tool)


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
    file_name: str               # conflict file's repo sub-path
    file_type: str               # 'Java' / 'Non-Java'
    valid_conflict: bool | None  # True = genuinely unresolvable conflict
    left_diff: str               # base -> left (xlsx snippet; reference)
    right_diff: str              # base -> right (xlsx snippet; reference)
    conflict_chunk: str          # xlsx MERGED snippet (used to select the annotated block)
    developer: str               # CHILD = ground-truth resolution (xlsx; fallback)

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
    commit: str
    tool: str                    # xlsx tool name (folder via tool_folder())
    tool_resolution: str         # xlsx tool snippet (clean code; fallback)
    developer: str               # xlsx CHILD snippet (unified diff; fallback)
    merged_snippet: str          # xlsx MERGED snippet (for select_target_block)
    desirable: bool              # human: tool resolution acceptable vs developer


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
        merged = _s(r[_C_MERGED])
        proj, commit = _s(r[_C_PROJECT]), _s(r[_C_COMMIT])
        for tool in TOOLS:
            _, desc_col, snip_col = _tool_columns(tool)
            label = _b(r[desc_col])
            if label is None:
                continue
            out.append(ManualLabel(proj, commit, tool, _s(r[snip_col]), dev, merged, label))
    return out


def clean_xlsx_snippet(s: str) -> str:
    """Return clean final code from an xlsx CODE SNIPPET cell.

    Version snippets (LEFT/RIGHT/CHILD) are unified diffs (@@ headers, +/- lines): apply them
    (drop '-' and '@@', strip the leading diff column from '+'/context). Tool snippets are
    already clean code: return as-is.
    """
    lines = (s or "").splitlines()
    is_diff = any(l.startswith("@@") for l in lines) or any(l.startswith("-") for l in lines)
    if not is_diff:
        return s or ""
    out = []
    for l in lines:
        if not l or l.startswith("@@"):
            continue
        if l[0] == "-":
            continue
        out.append(l[1:] if l[:1] in "+ " else l)
    return "\n".join(out)


# --- Resolved per-scenario files (fetched by scripts/fetch_data.py) -----------

def scenario_dir_for(project: str, commit: str) -> Path:
    return config.DATA_DIR / "scenarios" / f"{project}__{commit}"


def scenario_dir(s: Scenario) -> Path:
    return scenario_dir_for(s.project, s.commit)


def load_scenario_files(project: str, commit: str) -> dict[str, str]:
    """Return {ver: text} for every resolved file present (base/left/right/child + tool folders)."""
    d = scenario_dir_for(project, commit)
    out: dict[str, str] = {}
    for ver in _RESOLVED_VERS:
        p = d / ver
        if p.exists():
            out[ver] = p.read_text(encoding="utf-8", errors="replace")
    return out


def load_full_versions(s: Scenario) -> dict[str, str] | None:
    """Resolved files for a scenario, or None if base/left/right aren't all present."""
    out = load_scenario_files(s.project, s.commit)
    return out if {"base", "left", "right"} <= out.keys() else None
