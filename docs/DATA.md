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

### Why some scenarios are excluded (anchor_not_unique): a breakdown

Anchor-based extraction is purely textual (no Java parsing, by design -- keeps it
language-agnostic). On the 20 Scheme-A scenarios it excludes (`dev_status=
anchor_not_unique`, the 93 -> 72 step, alongside 1 EOL `no_conflict` case), the
cause splits four ways (see `scripts/diagnostics/classify_anchors.py`, and
`scripts/diagnostics/show_scenario.py` for a per-scenario view):

- **boundary_edge (8)** -- the conflict block touches the file START or END, so one
  side has fewer than K context lines to form an anchor while the other side is
  unique (e.g. `LoganSquare@a928069d`: block at EOF, `before` unique at k=4).
  These are the only safely-rescuable cases (a "unique anchor + file edge" rule
  would recover them, lifting the denominator 72 -> 80); left unchanged here to
  keep the extractor simple and the numbers stable.
- **duplicate_context (6)** -- the surrounding lines are repeated boilerplate
  (e.g. `closure-compiler@a506e4a7`, where `LINE_JOINER.join(` recurs in nearly
  every test method) that occurs many times in `child`, so the anchor matches
  >= 2 times. Genuine ambiguity; the guard correctly abstains.
- **adjacent_block_marker (4)** -- the file has multiple conflict blocks and the
  anchor window for the target block includes a neighbouring block's marker line
  (`<<<<<<<` etc.), so it can never match the marker-free `child` (e.g.
  `Terasology@f9957aa0`: 4 blocks, block #0's `after` anchor falls into block #1).
  A real limitation of the extractor in multi-block files (the MVP targets
  single-block scenarios; multi-block handling is out of scope).
- **rewrite_vanished (2)** -- the developer rewrote/moved the surrounding code, so
  the anchor lines genuinely do not exist in `child` (0 matches, marker-free).

In every case the guard excludes rather than guesses, so excluded scenarios never
contribute a possibly-wrong developer-match. Net effect: the developer-match
denominator is a conservative subset (72 of 93 in Scheme A), not a biased one.

## Detection Errata

Four tool detection labels are corrected in `conflictagent/data.py` through
`_DETECTION_OVERRIDES`. The xlsx is left unchanged; the code layers file-grounded corrections on
top of the original Strategy column.

## Known data edge case: EOL-induced false conflict (orientdb@501dac79)

Scenario `orientdb@501dac7919b0c0532b7849a010da46f7628fb2da`
(file `core/.../config/OGlobalConfiguration.java`, ConflictBench label
`Valid Conflict = True`) is excluded by our pipeline as `no_conflict`
(`status=no_conflict`, `dev_status=no_block`, both providers, both schemes).
Investigation shows this exclusion is correct: the recorded conflict is an
artifact of inconsistent line endings, not a semantic conflict.

Findings (each reproducible):

- **Line endings differ across the three sides.** `base` is UTF-8 with CRLF
  (682 lines); `left`, `right`, `child` are ASCII LF. (`file <ver>`,
  and a per-version carriage-return byte count.)
- **The CRLF is upstream, not introduced by ConflictBench.** The original
  OrientDB file at the merge-base commit is byte-identical to ConflictBench's
  `base` (md5 `c55919a15db9d18e51424fd150813876`, 32873 bytes). The base also
  carries an upstream Cyrillic homoglyph typo at L83 (`WAL_SYN` + U+0421 instead
  of ASCII `C`) that the `right` side later fixes; it merges cleanly and is
  unrelated to the conflict.
- **The conflict is entirely EOL-induced.** Controlled 3-way merge
  (`git merge -s recursive -X find-renames=90%`) with base content held constant
  and only its line endings toggled: CRLF base -> merge exits 1 (conflict);
  LF base (`tr -d '\r'`) -> merge exits 0 (clean). Single variable, result flips.
  After normalization, `left`'s and `right`'s real edits do not overlap.
- **Why the pipeline says `no_conflict`.** `data.load_scenario_files` reads via
  `read_text` (universal newlines), normalizing all sides to LF before
  reconstruction. The CRLF-driven conflict therefore disappears and
  `git merge-file` produces a clean merge.

Scope: a full scan of all 157 reconstructable scenarios on disk found that
`orientdb@501dac79` is the **only** scenario with inconsistent EOL among
`base/left/right`. Twelve other scenarios use CRLF or MIXED endings but
**consistently across all three sides**, so normalization keeps them aligned and
no false conflict arises (e.g. `fnlp@65492267` is uniformly MIXED, resolves
normally, and is excluded only by the `anchor_not_unique` guard -- unrelated to
EOL).

Interpretation (stated neutrally): ConflictBench faithfully recorded what a real
`git merge` produces on the unnormalized files; our pipeline normalizes EOL and
identifies that there is no semantic conflict. Net impact on results: one
scenario, already outside the comparable set -- negligible.
