"""Classify the `anchor_not_unique` scenarios by WHY developer-region extraction fails.

Background
----------
`groundtruth.resolution_region` locates the developer's resolution of a conflict
block inside the `child` file by using the K context lines just before `<<<<<<<`
and just after `>>>>>>>` as anchors (K tried in 3,4,5). A scenario is excluded
(`dev_status=anchor_not_unique`) when no K yields a unique before AND after match.

This script reproduces that control flow EXACTLY (including the
`len(before) < k or len(after) < k -> continue` boundary guard) and records, per
K, the precise failure reason, then buckets each scenario into FOUR causes:

  - boundary_edge        : one side has < K context lines because the block touches
                           the file START or END, while the other side matches
                           uniquely. Rescuable by "unique anchor + file edge".
                           (e.g. LoganSquare: block at EOF, before unique at k=4.)
  - adjacent_block_marker: an anchor window contains a conflict-marker line
                           (<<<<<<< / ||||||| / ======= / >>>>>>>) because another
                           conflict block sits within K lines. Such an anchor can
                           NEVER match the (marker-free) child -> guaranteed 0 hits.
                           A real limitation of the extractor in multi-block files.
                           (e.g. Terasology: 4 blocks, block #0's after touches #1.)
  - duplicate_context    : an anchor matched >= 2 times in child (repeated boilerplate
                           like `LINE_JOINER.join(` / `}` / `@Override`); never unique.
  - rewrite_vanished     : an anchor matched 0 times in child, was full length, and
                           was NOT marker-contaminated (developer rewrote/moved the
                           surrounding code so the anchor truly no longer exists).
  - would_be_ok / other  : fallbacks (would_be_ok should not appear for excluded ones).

Note: causes are not mutually exclusive across K; we pick by priority
adjacent_block_marker > duplicate_context > rewrite_vanished > boundary_edge,
so a marker-contaminated anchor is reported as such even if another K is edge-short.

Targets are read from the eval file (dev_status=anchor_not_unique), not hard-coded.

Run:
    python scripts/diagnostics/classify_anchors.py            # scheme A
    python scripts/diagnostics/classify_anchors.py --scheme B

Outputs (gitignored under outputs/):
    outputs/diagnostics/anchor_classification.txt    # human-readable
    outputs/diagnostics/anchor_classification.jsonl  # structured, one row per scenario
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from conflictagent import config, data, merge, groundtruth, validate  # noqa: E402

_ANCHOR_K = (3, 4, 5)  # mirrors groundtruth._ANCHOR_K
_MARKERS = ("<<<<<<<", "|||||||", "=======", ">>>>>>>")


def _has_marker(lines: list[str]) -> bool:
    return any(l.startswith(_MARKERS) for l in lines)


def target_ids(scheme: str) -> list[str]:
    """Scenario ids with dev_status=anchor_not_unique in the eval file (any provider)."""
    path = config.OUTPUT_DIR / "eval" / f"eval_{scheme}_complete.jsonl"
    if not path.exists():
        sys.exit(f"eval file not found: {path}")
    ids: set[str] = set()
    for line in path.open(encoding="utf-8"):
        r = json.loads(line)
        if r.get("kind") == "llm" and r.get("dev_status") == "anchor_not_unique":
            ids.add(r["id"])
    return sorted(ids)


def probe(merged: str, child: str, block_index: int) -> dict:
    """Re-run resolution_region's anchor search with full instrumentation."""
    mlines = merged.splitlines()
    starts = [i for i, l in enumerate(mlines) if l.startswith("<<<<<<<")]
    ends = [i for i, l in enumerate(mlines) if l.startswith(">>>>>>>")]
    rl = child.splitlines()

    if not starts or block_index >= len(starts):
        return {"verdict": "no_block", "n_blocks": len(starts), "ks": []}

    si, ei = starts[block_index], ends[block_index]
    at_file_start = si < max(_ANCHOR_K)
    at_file_end = (len(mlines) - 1 - ei) < max(_ANCHOR_K)

    ks = []
    would_ok = False
    saw_marker = False     # an anchor window contained a conflict marker line
    saw_dup = False        # an anchor matched >= 2 times
    saw_vanish = False     # an anchor matched 0 times, full length, marker-free
    saw_edge = False       # a K was short on one side due to file boundary

    for k in _ANCHOR_K:
        before = mlines[si - k:si] if si - k >= 0 else mlines[:si]
        after = mlines[ei + 1:ei + 1 + k]
        rec = {"k": k, "before_len": len(before), "after_len": len(after),
               "before_has_marker": _has_marker(before),
               "after_has_marker": _has_marker(after)}

        if _has_marker(before) or _has_marker(after):
            saw_marker = True

        if len(before) < k or len(after) < k:
            rec["status"] = "edge_short"
            rec["short_side"] = ("before" if len(before) < k else "") + \
                                ("after" if len(after) < k else "")
            saw_edge = True
            ks.append(rec)
            continue

        before_hits = sum(1 for i in range(len(rl) - k + 1) if rl[i:i + k] == before)
        rec["before_hits"] = before_hits
        if before_hits != 1:
            rec["status"] = "before_not_unique"
            if before_hits >= 2:
                saw_dup = True
            elif not _has_marker(before):
                saw_vanish = True
            ks.append(rec)
            continue

        bpos = next(i for i in range(len(rl) - k + 1) if rl[i:i + k] == before)
        start = bpos + k
        after_hits = sum(1 for j in range(start, len(rl) - k + 1) if rl[j:j + k] == after)
        rec["after_hits"] = after_hits
        if after_hits != 1:
            rec["status"] = "after_not_unique"
            if after_hits >= 2:
                saw_dup = True
            elif not _has_marker(after):
                saw_vanish = True
            ks.append(rec)
            continue

        rec["status"] = "ok"
        would_ok = True
        ks.append(rec)
        break

    # ---- classify by priority ----
    if would_ok:
        verdict = "would_be_ok"
    elif saw_marker:
        verdict = "adjacent_block_marker"
    elif saw_dup:
        verdict = "duplicate_context"
    elif saw_vanish:
        verdict = "rewrite_vanished"
    elif saw_edge and (at_file_start or at_file_end):
        verdict = "boundary_edge"
    else:
        verdict = "other"

    return {
        "verdict": verdict,
        "n_blocks": len(starts),
        "at_file_start": at_file_start,
        "at_file_end": at_file_end,
        "ks": ks,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scheme", default="A", choices=["A", "B"])
    args = ap.parse_args()

    ids = target_ids(args.scheme)
    scen_by_key = {f"{s.project}@{s.commit}": s for s in data.load_scenarios()}

    out_dir = config.OUTPUT_DIR / "diagnostics"
    out_dir.mkdir(parents=True, exist_ok=True)
    txt_path = out_dir / "anchor_classification.txt"
    jsonl_path = out_dir / "anchor_classification.jsonl"

    rows = []
    body = []
    for sid in ids:
        proj, short = sid.split("@")
        s = next((sc for key, sc in scen_by_key.items()
                  if key.split("@")[0] == proj and key.split("@")[1].startswith(short)), None)
        if s is None:
            body.append(f"{sid}: SCENARIO NOT FOUND")
            continue
        fv = data.load_full_versions(s)
        if fv is None:
            body.append(f"{sid}: base/left/right not on disk")
            continue
        merged, _ = merge.reconstruct_merged(fv["base"], fv["left"], fv["right"])
        bi, ov = groundtruth.select_target_block(merged, s.conflict_chunk)
        info = probe(merged, fv["child"], bi)
        info.update({"id": sid, "block_index": bi, "xlsx_overlap": round(ov, 2),
                     "file_name": s.file_name})
        rows.append(info)

        body.append(f"\n=== {sid}  [{info['verdict']}] ===")
        body.append(f"  file: {s.file_name}")
        body.append(f"  blocks={info['n_blocks']} target=#{bi} (xlsx overlap {ov:.2f}) "
                    f"at_file_start={info['at_file_start']} at_file_end={info['at_file_end']}")
        for rec in info["ks"]:
            extra = " ".join(f"{kk}={vv}" for kk, vv in rec.items()
                             if kk not in ("k", "status"))
            body.append(f"    k={rec['k']:>1} {rec['status']:<18} {extra}")

    counts = Counter(r["verdict"] for r in rows)
    rescuable = counts.get("boundary_edge", 0)
    header = [
        f"anchor_not_unique classification (scheme {args.scheme}); {len(ids)} scenarios",
        "",
        "SUMMARY: " + ", ".join(f"{v}={n}" for v, n in counts.most_common()),
        f"boundary_edge is the only safely-rescuable class: saving it would raise the "
        f"dev-match denominator by {rescuable} (scheme A: 72 -> {72 + rescuable}).",
        "adjacent_block_marker = extractor limitation in multi-block files (anchor caught a "
        "marker line). duplicate_context / rewrite_vanished are genuine ambiguity.",
        "",
    ]

    text = "\n".join(header + body) + "\n"
    txt_path.write_text(text, encoding="utf-8")
    with jsonl_path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    print("\n".join(header))
    print(f"wrote {txt_path}")
    print(f"wrote {jsonl_path}")


if __name__ == "__main__":
    main()
