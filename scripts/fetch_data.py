"""Pull ConflictBench data into ./data (gitignored).

Minimum for region-only input: ConflictBench.xlsx (has all LEFT/RIGHT/MERGED/CHILD
snippets + labels, 180 scenarios). The full scenario folders are only needed later
for local syntax validation, so they're fetched lazily then — not here.

Run:  python scripts/fetch_data.py
"""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

# Allow running as a plain script: make the package importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from conflictagent import config  # noqa: E402


def download(url: str, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "ConflictAgent-fetch"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(dst, "wb") as f:
        f.write(resp.read())


def main() -> None:
    url = f"{config.CONFLICTBENCH_RAW}/Data/ConflictBench.xlsx"
    dst = config.CONFLICTBENCH_XLSX
    print(f"Downloading {url}")
    download(url, dst)
    size = dst.stat().st_size
    valid_xlsx = dst.read_bytes()[:2] == b"PK"   # .xlsx is a zip archive
    print(f"  -> {dst}  ({size} bytes, valid_xlsx={valid_xlsx})")
    if not valid_xlsx:
        raise SystemExit("Downloaded file is not a valid .xlsx — aborting.")


if __name__ == "__main__":
    main()
