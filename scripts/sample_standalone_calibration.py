"""Standalone-judge calibration: sample resolutions for a human to label, then score agreement.

WHY: the standalone-valid desirability numbers (87-93%) rest on judge.judge_standalone, which —
unlike the developer-match judge v2 (calibrated on 627 human labels) — has NOT been validated
against human judgment. This builds a blind labeling sheet so Bowen can judge a sample by hand,
then measures how well the LLM judge agrees (accuracy / precision / recall vs Bowen's labels).

The 627 ConflictBench labels are developer-match labels (is a resolution desirable vs the
developer), which is a DIFFERENT question from standalone ("is this a sensible merge, no
reference"), so they can't be reused — standalone needs its own fresh human labels.

TWO MODES
  generate : sample N scenarios (balanced over valid_conflict), regenerate the resolution with the
             real pipeline (temperature=0, so ~identical to the eval run), get the judge's verdict,
             and write:
               outputs/calib/standalone_sample_<stamp>.md       <- BLIND sheet you fill in
               outputs/calib/standalone_sample_<stamp>_key.jsonl <- judge verdicts (don't peek)
             In the .md, after each item write  VERDICT: yes   or   VERDICT: no.
  score    : read your filled-in .md + the key, print agreement / precision / recall and list
             every disagreement (those are what tells us how to fix the standalone prompt).

RUN
  python scripts/sample_standalone_calibration.py generate --provider openai --n 40
  # ... hand-label the .md ...
  python scripts/sample_standalone_calibration.py score outputs/calib/standalone_sample_<stamp>.md
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from conflictagent import config, data, agent, groundtruth, judge, merge, validate  # noqa: E402


def _indent(text: str) -> str:
    return "\n".join("    " + l for l in (text or "(empty)").splitlines()) or "    (empty)"


def generate(args) -> None:
    pool = []
    for s in data.load_scenarios(java_only=True):
        fv = data.load_full_versions(s)
        if not fv:
            continue
        merged, _ = merge.reconstruct_merged(fv["base"], fv["left"], fv["right"])
        blocks = validate.conflict_blocks(merged)
        tgt, _ = groundtruth.select_target_block(merged, s.conflict_chunk)
        if tgt < 0 or tgt >= len(blocks):
            continue
        pool.append((s, fv, blocks[tgt]))

    # Balanced sample over valid_conflict (true vs false conflict), fixed seed = reproducible.
    rng = random.Random(args.seed)
    true_p = [x for x in pool if x[0].valid_conflict]
    false_p = [x for x in pool if not x[0].valid_conflict]
    rng.shuffle(true_p); rng.shuffle(false_p)
    half = args.n // 2
    pick = true_p[:half] + false_p[: args.n - half]
    if len(pick) < args.n:  # top up if one stratum is short
        rest = [x for x in (true_p[half:] + false_p[args.n - half:])]
        rng.shuffle(rest)
        pick += rest[: args.n - len(pick)]
    rng.shuffle(pick)

    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_dir = config.OUTPUT_DIR / "calib"
    out_dir.mkdir(parents=True, exist_ok=True)
    sheet = out_dir / f"standalone_sample_{stamp}.md"
    key = out_dir / f"standalone_sample_{stamp}_key.jsonl"

    print(f"Generating {len(pick)} items | provider={args.provider} | judge={config.JUDGE_MODEL[1]}")
    with open(sheet, "w", encoding="utf-8") as sh, open(key, "w", encoding="utf-8") as kf:
        sh.write("# Standalone judge — blind labeling sheet\n\n"
                 "For each item: read the conflict (LEFT/BASE/RIGHT) and the CANDIDATE.\n"
                 "Is the CANDIDATE an ACCEPTABLE resolution — a sensible merge that honors both\n"
                 "sides where compatible, no leftover conflict markers, syntactically plausible?\n"
                 "Write `VERDICT: yes` or `VERDICT: no` after each item. Do NOT open the _key file.\n\n")
        for i, (s, fv, block) in enumerate(pick, 1):
            left, base, right = validate.split_diff3_block(block)
            rec = agent.resolve(args.provider, s, fv, scheme="A")
            cand = rec.get("final_resolution", "") or ""
            v = judge.judge_standalone(cand, left, base, right)
            sh.write(f"## Item {i} — id: {s.id}  (valid_conflict={s.valid_conflict})\n\n"
                     f"### LEFT\n{_indent(left)}\n\n### BASE\n{_indent(base)}\n\n"
                     f"### RIGHT\n{_indent(right)}\n\n### CANDIDATE\n{_indent(cand)}\n\n"
                     f"VERDICT: \nNOTES: \n\n---\n\n")
            kf.write(json.dumps({"item": i, "id": s.id, "valid_conflict": s.valid_conflict,
                                 "judge_verdict": v["equivalent"], "judge_reason": v["reason"]},
                                ensure_ascii=False) + "\n")
            print(f"  [{i}/{len(pick)}] {s.id}  judge={v['equivalent']}")
    print(f"\nBLIND sheet -> {sheet}\nKEY (don't peek) -> {key}")


def score(args) -> None:
    sheet = Path(args.sheet)
    key = Path(args.key) if args.key else sheet.with_name(sheet.stem + "_key.jsonl")
    if not sheet.exists():
        print(f"Sheet not found: {sheet}\n"
              f"Run `generate` first (it calls the model + judge and prints the exact paths), "
              f"then label that .md, then score it.")
        return
    if not key.exists():
        print(f"Key not found: {key}\n"
              f"The key is written by `generate` alongside the sheet — so run `generate` first. "
              f"(A hand-created .md has no matching key.)")
        return
    krows = {r["id"]: r for r in (json.loads(l) for l in open(key) if l.strip())}

    text = open(sheet, encoding="utf-8").read()
    # Parse "## Item N — id: <id>" ... "VERDICT: yes/no" per block.
    human = {}
    for block in re.split(r"^## Item ", text, flags=re.M)[1:]:
        mid = re.search(r"id:\s*(\S+)", block)
        mv = re.search(r"VERDICT:\s*(yes|no|y|n|true|false)", block, re.I)
        if mid and mv:
            human[mid.group(1)] = mv.group(1).lower() in ("yes", "y", "true")

    tp = fp = tn = fn = 0
    disagree = []
    n = 0
    for cid, h in human.items():
        if cid not in krows:
            continue
        j = krows[cid]["judge_verdict"]
        if j is None:
            continue
        n += 1
        if j and h: tp += 1
        elif j and not h: fp += 1
        elif not j and not h: tn += 1
        else: fn += 1
        if j != h:
            disagree.append((cid, f"judge={j} human={h}", krows[cid].get("judge_reason", "")))

    acc = (tp + tn) / n if n else 0.0
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    print(f"Labeled & keyed: {n}")
    print(f"  agreement(acc) = {acc:.1%}   precision = {prec:.1%}   recall = {rec:.1%}")
    print(f"  confusion: judge-accept&human-accept={tp}  judge-accept&human-reject={fp}  "
          f"judge-reject&human-reject={tn}  judge-reject&human-accept={fn}")
    if disagree:
        print("\nDisagreements (drive the prompt fix):")
        for cid, d, why in disagree:
            print(f"  {cid:30s} {d}  judge_reason: {why}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate")
    g.add_argument("--provider", default="openai")
    g.add_argument("--n", type=int, default=40)
    g.add_argument("--seed", type=int, default=0)
    sc = sub.add_parser("score")
    sc.add_argument("sheet")
    sc.add_argument("--key", default=None)
    args = ap.parse_args()
    (generate if args.cmd == "generate" else score)(args)


if __name__ == "__main__":
    main()
