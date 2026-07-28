# Data Notes

## Source

ConflictAgent uses ConflictBench as its data source. `scripts/fetch_data.py` downloads:

- `data/ConflictBench.xlsx`;
- complete scenario files under `data/scenarios/{project}__{commit}/`.

The data directory is gitignored.

## Scenario Counts

- 180 textual conflict scenarios.
- 135 true conflicts, 45 false conflicts (orientdb@501dac79 reclassified True -> False: its
  "conflict" is an EOL artifact that `git merge` resolves cleanly after normalization -- see
  "Known data edge case" below. Note: ConflictBench's published xlsx still labels it True; this
  count reflects the corrected classification. The reclassification has no effect on any computed
  result -- orientdb is already excluded upstream as no_conflict.)
- 106 Java scenarios.
- 93 reconstructable Java scenarios with base/left/right file available.

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

In ConflictBench.xlsx, Version snippets such as LEFT/RIGHT/CHILD are unified-diff-like snippets, 
not always clean final code. Tool snippets are usually clean code. Prefer complete files 
when possible; use cleaned xlsx snippets only as fallback.

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

## FSTMerge detection classification & known labeling gaps (2026-07-25 audit)

> **Scope: this is a ConflictBench (upstream benchmark) labeling matter — a legacy of that
> project, not a ConflictAgent defect.** ConflictAgent only *consumes* ConflictBench's
> `{Tool} Strategy` / desirability labels; the gaps below live in the benchmark's manual
> annotation. Recorded here because ConflictAgent depends on those labels — and to show they do
> **not** affect any ConflictAgent result (proven zero-impact below). Any actual fix belongs
> upstream in ConflictBench, not here.

**Ideal Detection-vs-Resolution rule:** a tool output is a scored Resolution only if the FINAL
target file exists AND has no conflict markers; markers present -> Detection (desirability N/A);
only `result.txt` (human-added to run the tool) or only a `.merge` intermediate -> Not Applied.

**How ConflictBench's labels diverge from this ideal rule (FSTMerge):**
- ~62 "generate nothing" pairs that, by the ideal rule, should be N/A rather than 0.
- 2 outright mislabels: `graphql-java@4cfd6281` and `RxLifecycle@30410d56` — a clean, marker-free
  final target file exists, yet labeled "generate nothing" (should be a scored Resolution).
- An NA-vs-"generate nothing" split among no-target cases (same reality, two labels).

**Why ConflictAgent does NOT relabel or re-run (proven zero impact):** all 62 "generate nothing"
pairs are already excluded from the judge set as empty-region drops; relabeling 0->N/A only swaps
which filter removes them — they never enter the n=292 set either way, so precision (100%),
recall (64.6%), and the headline stay unchanged. The 2 mislabels are likewise currently excluded
(empty xlsx snippet); fixing them would additionally require repairing the nested-path extraction
(FSTMerge output lives at `FSTMerge/merge/<full/path>/File.ext`, never found by the flat-name
loader) and would add just 2 pairs to ~305. Documented for traceability.

## Judge-line input pipeline (Scheme A, 2026-07): file-level gate, is_diff fix, residual scope-mismatch

The judge meta-evaluation funnel (`build_metaevaluation_testcases`) is
`627 → −253 punt → −22 file-level → −60 empty → 292`. Two 2026-07 changes hardened the input
pipeline; both are ConflictAgent-side and leave the raw ConflictBench xlsx untouched.

**(1) Scenario-level file-level gate ("B gate").** A conflict is judgeable only if ConflictBench
provides a complete `base`/`left`/`right` 3-way for the file. When any of the three is missing the
scenario is a file-level `add` / `delete` / `rename` / `add-add` operation (23 scenarios: 13 Java +
10 non-Java), with no reconstructable in-file conflict — its xlsx merged/child are git messages
(`--- a/`, `+++ /dev/null`, `rename ...`) or whole-file blobs, not a region resolution. The gate
(`{"base","left","right"} <= load_scenario_files(...).keys()`, scenario-level, all five tools) drops
them. This is the SAME structural check the solver line applies at 106→93. The missing-version
signature also classifies the operation: base+left present / right missing = right deleted;
base+right / left missing = left deleted; base missing / left+right present = add-add;
base+left missing / right present = rename.

**(2) is_diff fix in `clean_xlsx_snippet`.** The xlsx CHILD/tool snippets are unified-diff-like. The
old is_diff heuristic (`any '@@' or any '-' line`) missed *pure-add / context-only* hunks (no `-`,
no `@@`), returning them verbatim with a `+` on every added line — so `+`-prefixed "developer" text
reached the judge. The fix treats a hunk as a diff when every non-blank line is a diff column
(space/+/-) and at least one is a `+`, guarded so it never mis-strips already-clean code or markdown
bullets. This recovered 39 pure-add inputs (each becomes clean code once the diff column is
stripped), lifting judge recall 61.7 → 64.6 with precision unchanged at 100%.

Together these two account for the earlier "48 contaminated judge inputs": 9 are genuine non-code
git messages (dropped by the B gate as file-level ops) and 39 are recoverable pure-add code (cleaned
by the is_diff fix).

**Residual known limitation (documented, not fixed): scope-mismatched xlsx pairs.** A minority of
xlsx pairs record the candidate and developer at inconsistent scopes/windows — e.g.
`incubator-shardingsphere@7fe148b3`, where the developer is a 2-line diff window while the
IntelliMerge candidate is the full 24-line import block; or `jjwt@3f079803`, where the child is the
whole 29-line file vs an 8-line merged region. Comparing across mismatched spans can only make the
judge *reject* a valid resolution (depressing recall), never produce a false accept, so precision
stays 100%. There is no clean automatic detector (a candidate/developer size-ratio screen flags ~45
pairs, most of which are legitimate large tool-vs-developer resolution differences, not recording
defects), so these are left in and documented rather than hand-excluded — consistent with the
conservative-lower-bound framing.

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
