# Data Notes

## Source

ConflictAgent uses ConflictBench as its data source. `scripts/fetch_data.py` downloads:

- `data/ConflictBench.xlsx`;
- complete scenario files under `data/scenarios/{project}__{commit}/`.

The data directory is gitignored.

## Scenario Counts

- 180 textual conflict scenarios.
- 136 true conflicts, 44 false conflicts.
- 106 Java scenarios.
- 93 reconstructable Java scenarios with base/left/right available.

## Versions

Each reconstructable scenario can include:

- `base`: common ancestor;
- `left`: one branch;
- `right`: the other branch;
- `child`: developer resolution;
- `FSTMerge`, `JDime`, `IntelliMerge`, `AutoMerge`, `KDiff3`: tool outputs when present.

## Important Xlsx Columns

- `Project`
- `Commit`
- `File Name`
- `File Type`
- `Valid Conflict`
- `LEFT VERSION\nCODE SNIPPET`
- `RIGHT VERSION\nCODE SNIPPET`
- `MERGED VERSION\nCODE SNIPPET`
- `CHILD VERSION\nCODE SNIPPET`
- `{Tool}_Desirability_Same_Developper`
- `{Tool} Strategy`
- `{Tool}\nCODE SNIPPET`

The `Developper` spelling is from the source file and is intentionally preserved in code.

## Snippet Gotchas

Version snippets such as LEFT/RIGHT/CHILD are unified-diff-like snippets, not always clean final
code. Tool snippets are usually clean code. Prefer complete files when possible; use cleaned xlsx
snippets only as fallback.

## Target Block Selection

Files may contain more than one conflict block. ConflictAgent does not blindly use block 0. It
selects the target block by matching content lines from the xlsx `MERGED VERSION` snippet against
the reconstructed diff3 blocks.

## Developer Region Extraction

The developer resolution is extracted from the `child` file using context anchors around the target
block in the reconstructed merged file. If anchors are not unique, the scenario is excluded from
developer-match rather than guessed.

## Detection Errata

Four tool detection labels are corrected in `conflictagent/data.py` through
`_DETECTION_OVERRIDES`. The xlsx is left unchanged; the code layers file-grounded corrections on
top of the original Strategy column.
