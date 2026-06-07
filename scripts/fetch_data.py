"""Pull ConflictBench data into ./data (gitignored).

Minimum for region-only input: ConflictBench.xlsx (has all LEFT/RIGHT/MERGED/CHILD
snippets + labels). Full scenario folders are only needed later for local syntax
validation, so fetch them lazily / on demand rather than cloning everything.

TODO:
  - download {CONFLICTBENCH_RAW}/Data/ConflictBench.xlsx -> DATA_DIR
  - (optional) sparse-fetch a scenario's full file when validate.py needs it
"""

if __name__ == "__main__":
    raise SystemExit("fetch_data: not implemented yet")
