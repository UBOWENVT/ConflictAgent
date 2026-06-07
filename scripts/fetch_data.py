"""Pull ConflictBench data into ./data (gitignored).

  1. ConflictBench.xlsx -> data/  (snippets + labels + developer ground truth)
  2. Per-scenario full files (base/left/right/child) -> data/scenarios/{project}__{commit}/{ver}
     for every scenario whose conflict File Name exists in base+left+right (157/180; the rest
     are add/delete/rename cases that can't be 3-way reconstructed at the file level).

The full files feed merge.reconstruct_merged() + validate.syntax_valid().

Run:  python scripts/fetch_data.py             # xlsx + all reconstructable scenarios
      python scripts/fetch_data.py --limit 5   # quick: xlsx + first 5 scenarios
      python scripts/fetch_data.py --xlsx-only
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from conflictagent import config  # noqa: E402

VERS = ("base", "left", "right", "child")
_TREE_API = "https://api.github.com/repos/UBOWENVT/ConflictBench/git/trees/master?recursive=1"


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "ConflictAgent-fetch"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def fetch_xlsx() -> None:
    dst = config.CONFLICTBENCH_XLSX
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(_get(f"{config.CONFLICTBENCH_RAW}/Data/ConflictBench.xlsx"))
    if dst.read_bytes()[:2] != b"PK":
        raise SystemExit("Downloaded file is not a valid .xlsx")
    print(f"  xlsx -> {dst} ({dst.stat().st_size} bytes)")


def _tree_blobs() -> set[str]:
    """Set of all blob paths in the repo (cached to data/_tree.json)."""
    cache = config.DATA_DIR / "_tree.json"
    if cache.exists():
        tree = json.loads(cache.read_text())
    else:
        tree = json.loads(_get(_TREE_API).decode("utf-8"))
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(tree))
    return {t["path"] for t in tree["tree"] if t["type"] == "blob"}


def fetch_scenarios(limit: int | None = None) -> None:
    from conflictagent import data  # requires the xlsx to be downloaded first

    blobs = _tree_blobs()
    out_dir = config.DATA_DIR / "scenarios"
    done = skipped = 0
    for s in data.load_scenarios():
        repo_paths = {
            ver: f"Resource/merge_scenarios/{s.project}/{s.commit}/{ver}/{s.file_name}"
            for ver in VERS
        }
        if not all(repo_paths[v] in blobs for v in ("base", "left", "right")):
            skipped += 1
            continue
        sdir = out_dir / f"{s.project}__{s.commit}"
        sdir.mkdir(parents=True, exist_ok=True)
        for ver in VERS:
            if repo_paths[ver] not in blobs:
                continue
            dst = sdir / ver
            if not dst.exists():
                dst.write_bytes(_get(f"{config.CONFLICTBENCH_RAW}/{urllib.parse.quote(repo_paths[ver])}"))
        done += 1
        print(f"  [{done}] {s.id}  ({s.file_type})")
        if limit and done >= limit:
            break
    print(f"Fetched {done} scenarios into {out_dir}"
          + (f" (skipped {skipped} non-reconstructable so far)" if not limit else ""))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="only fetch the first N scenarios")
    ap.add_argument("--xlsx-only", action="store_true", help="download just the xlsx")
    args = ap.parse_args()
    fetch_xlsx()
    if not args.xlsx_only:
        fetch_scenarios(limit=args.limit)


if __name__ == "__main__":
    main()
