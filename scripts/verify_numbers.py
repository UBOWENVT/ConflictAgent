"""Recompute the reported ConflictAgent numbers from the frozen results in results/.

The stage-3 figures (the agent setting, docs/HARNESS.md) are recomputed from the
results/stage3_* files the same way, including the failure analysis: its label counts, the
spot-check agreement and the process cross-tabs.

No API key, no LLM calls, standard library only:

    python scripts/verify_numbers.py

Each figure is recomputed from the per-case files and compared with the value quoted in README.md and
docs/RESULTS.md (those quoted values are kept in EXPECTED below; change both together). Before that,
the files are checked against their committed sha256, for duplicate rows, and for verdicts that
disagree with their scores at the 0.5 threshold. The script exits with status 1 if any check fails. The LLM-vs-tools table also needs the
ConflictBench labels (which tool outputs were left unresolved); see docs/REPRODUCE.md.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from decimal import ROUND_HALF_UP, Decimal
from math import comb
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JUDGE_FILE = ROOT / "results" / "meta_evaluation_20260727_062930.jsonl"
SOLVER_FILE = ROOT / "results" / "solver_eval_20260627_095221.jsonl"

# Values as quoted in README.md / docs/RESULTS.md.
EXPECTED = {
    "judge: labeled cases": "292",
    "judge: TP / FP / TN / FN": "117 / 0 / 111 / 64",
    "judge: precision": "100.0%",
    "judge: recall": "64.6%",
    "judge: accuracy": "78.1%",
    "solver: records (scenario x provider)": "132",
    "solver dev-match, true, openai": "27/49 = 55.1%",
    "solver dev-match, true, gemini": "29/47 = 61.7%",
    "solver dev-match, true, floor (reported)": "55.1%",
    "solver dev-match, true, pooled": "56/96 = 58.3%",
    "solver dev-match, false, openai": "12/18 = 66.7%",
    "solver dev-match, false, gemini": "11/18 = 61.1%",
    "structural validity, true": "92/96 = 95.8%",
    "structural validity, false": "35/36 = 97.2%",
    "structural failures accepted by judge (1)": "4 of 5",
}
THRESHOLD = 0.5  # GEval score -> verdict cutoff used for both runs (score >= threshold = accept)
BOUNDARY = 1e-3  # stored scores are rounded; verdicts this close to the cutoff are not re-checked
SHA256 = {  # the frozen files as committed; a mismatch means they were changed after publication
    "meta_evaluation_20260727_062930.jsonl": "1c2f64a3d63bf21e072c9ebee952bd36faca934383fca5e2e6572968c1ba1a8f",
    "solver_eval_20260627_095221.jsonl": "f03a9219fdb4f58222538f43937b88f269abd6d908eff0e277725f550bc2fd36",
    "stage3_unified_eval_20261010_163404.jsonl": "b7b1627e22034d65ede98b868219c84cf4d3d1dad401498eae62165c1e94e64c",
    "stage3_agent_metrics_20261010.csv": "8429d67e1ba346309438b7c5ff430bf9ee071cd90bb42d08d93183146e066c55",
    "stage3_single_shot_20261010.csv": "e93e6100a14996080bb102ca5f5c65f6d15a44def56845315d58343e732b89cc",
    "stage3_failure_labels_20261012.csv": "745167841b1125761331b9573fad205f03bc1443e6c1b68f9050e474f938d474",
    "stage3_process_signals_20261012.csv": "d80220f93051d78899b77f9021d71275b7728798a1c76a4b02820e99eacb90af",
}

# Stage 3: the agent setting (docs/HARNESS.md "Results").
S3_UNIFIED = ROOT / "results" / "stage3_unified_eval_20261010_163404.jsonl"
S3_AGENT = ROOT / "results" / "stage3_agent_metrics_20261010.csv"
S3_SINGLE = ROOT / "results" / "stage3_single_shot_20261010.csv"
S3_LABELS = ROOT / "results" / "stage3_failure_labels_20261012.csv"
S3_SIGNALS = ROOT / "results" / "stage3_process_signals_20261012.csv"
PRESTO = "presto@f50b46c7"
N_TYPE = {True: 49, False: 18}
# Secondary convention per outcome; must equal harness/scorers.py OUTCOME_RULES (a test checks it).
SECONDARY = {"gradeable": "judge", "empty": "exclude", "no_edit": "exclude", "unfinished": "exclude",
             "markers": "miss", "out_of_block": "judge", "not_extractable": "exclude",
             "error": "exclude"}
AGENT_MODEL = {"openai": "openai/gpt-5.4-2026-03-05", "gemini": "google/gemini-3.5-flash"}
EXPECTED_STAGE3 = {
    "s3 agent: samples / errors / gradeable / empty": "134 / 0 / 131 / 3",
    "s3 single-shot rerun: records / errors / empty": "134 / 0 / 0",
    "s3 unified: verdict rows / judge calls": "402 / 397",
    "s3 (1) agent, true, openai": "26/49 = 53.1%",
    "s3 (1) agent, true, gemini": "32/49 = 65.3%",
    "s3 (1) agent, false, openai": "13/18 = 72.2%",
    "s3 (1) agent, false, gemini": "11/18 = 61.1%",
    "s3 (1) single_shot, true, openai": "23/49 = 46.9%",
    "s3 (1) single_shot, true, gemini": "35/49 = 71.4%",
    "s3 (1) single_shot, false, openai": "12/18 = 66.7%",
    "s3 (1) single_shot, false, gemini": "11/18 = 61.1%",
    "s3 (1) june, true, openai": "27/49 = 55.1%",
    "s3 (1) june, true, gemini": "29/49 = 59.2%",
    "s3 (1) june, false, openai": "12/18 = 66.7%",
    "s3 (1) june, false, gemini": "11/18 = 61.1%",
    "s3 (1) lower provider, true: agent / single_shot / june": "53.1% / 46.9% / 55.1%",
    "s3 (1) without presto, agent": "26/48 = 54.2% / 32/48 = 66.7%",
    "s3 (1) without presto, single_shot": "22/48 = 45.8% / 34/48 = 70.8%",
    "s3 (1) without presto, june": "26/48 = 54.2% / 29/48 = 60.4%",
    "s3 (1) secondary: agent openai / agent gemini / june gemini": "26/48 = 54.2% / 32/47 = 68.1% / 29/47 = 61.7%",
    "s3 paired agent vs single_shot, openai": "18 / 8 / 5 / 18, p = 0.58",
    "s3 paired agent vs single_shot, gemini": "31 / 1 / 4 / 13, p = 0.38",
    "s3 paired without presto, openai": "18 / 8 / 4 / 18, p = 0.39",
    "s3 paired without presto, gemini": "31 / 1 / 3 / 13, p = 0.63",
    "s3 judge drift (june vs frozen June)": "132/132 unchanged; 23 scores moved, max 0.2",
    "s3 model drift single_shot vs june, gemini": "6 vs 0, p = 0.031",
    "s3 model drift without presto, gemini": "5 vs 0, p = 0.063",
    "s3 model drift single_shot vs june, openai": "2 vs 6, p = 0.29",
    "s3 (2) agent openai: single / multi": "32/32 = 100% / 16/16 = 100%",
    "s3 (2) agent gemini: single / multi": "31/32 = 96.9% / 15/15 = 100%",
    "s3 (2) single_shot openai: single / multi": "31/33 = 93.9% / 16/16 = 100%",
    "s3 (2) single_shot gemini: single / multi": "32/33 = 97.0% / 16/16 = 100%",
    "s3 (2) june openai: single / multi": "30/33 = 90.9% / 16/16 = 100%",
    "s3 (2) june gemini: single / multi": "30/31 = 96.8% / 16/16 = 100%",
    "s3 calls per scenario, mean (max): agent openai / gemini": "4.7 (14) / 10.6 (27)",
    "s3 calls per scenario, mean (max): single-shot openai / gemini": "1.19 (4) / 1.10 (4)",
    "s3 call ratio agent / single-shot, rounded: openai / gemini": "4 / 10",
    "s3 tool calls bash/view/replace/check: openai": "26 / 293 / 75 / 68",
    "s3 tool calls bash/view/replace/check: gemini": "256 / 234 / 74 / 81",
    "s3 ran check_java at least once: openai / gemini": "67/67 / 67/67",
    "s3 passed check_java only after failing it: openai / gemini": "0 / 6",
    "s3 limits hit: openai / gemini": "0 / 1",
    "s3 tool errors: openai / gemini": "8 / 2",
    "s3 working time per sample, mean: openai / gemini": "11.6 s / 45.2 s",
    "s3 agent cost: openai / gemini / total": "$2.36 / $3.79 / $6.15",
    "s3 single-shot cost estimate: openai / gemini": "$0.85 / $0.20",
    "s3 gate: not extractable / out of block / limits hit": "0/134 / 0/134 / 1/134",
}
# Failure analysis (docs/HARNESS.md "Failure analysis"); codes in the codebook's precedence order.
CODES = ("E3", "E2", "E1", "M1", "M5", "M4", "M3", "M2")
EXPECTED_FAILURES = {
    "s3 failures: agent misses openai / gemini / total": "28 / 24 / 52",
    "s3 failures E3/E2/E1/M1/M5/M4/M3/M2: openai": "2 / 0 / 6 / 5 / 1 / 1 / 3 / 10",
    "s3 failures E3/E2/E1/M1/M5/M4/M3/M2: gemini": "2 / 2 / 2 / 4 / 1 / 1 / 1 / 11",
    "s3 failures E3/E2/E1/M1/M5/M4/M3/M2: total": "4 / 2 / 8 / 9 / 2 / 2 / 4 / 21",
    "s3 failures: evaluation side (E)": "14/52",
    "s3 failures: E1 also missed by single-shot": "8/8",
    "s3 failures: M2 on import-only blocks": "10 of 21",
    "s3 failures: false conflicts M2 / M1 / M4": "9 / 2 / 1 of 12",
    "s3 failures: single-shot only M3 / M1 / M6": "7 / 2 / 1 of 10",
    "s3 failures: agent only E / M2 / M1 / M3 / M4": "3 / 3 / 1 / 1 / 1 of 9",
    "s3 spot check: round 1 / round 2 / round 2 unseen / all": "3/8 / 4/7 / 3/4 / 7/15",
    "s3 signals: openai searched, accepted yes / no, Fisher p": "13/18 = 72% / 26/49 = 53%, p = 0.18",
    "s3 signals: gemini probed, accepted yes / no, Fisher p": "11/20 = 55% / 32/47 = 68%, p = 0.40",
    "s3 signals: gemini checked before editing / read checker source": "6/67 / 1/67",
    "s3 signals: searched openai / gemini; probed openai / gemini": "18/67 / 66/67; 0/67 / 20/67",
}


def _load(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _frac(a: int, n: int) -> str:
    return f"{a}/{n} = {a / n:.1%}"


def recompute() -> dict[str, str]:
    got: dict[str, str] = {}

    judge = _load(JUDGE_FILE)
    tp = sum(1 for r in judge if r["judge"] and r["human"])
    fp = sum(1 for r in judge if r["judge"] and not r["human"])
    tn = sum(1 for r in judge if not r["judge"] and not r["human"])
    fn = sum(1 for r in judge if not r["judge"] and r["human"])
    got["judge: labeled cases"] = str(len(judge))
    got["judge: TP / FP / TN / FN"] = f"{tp} / {fp} / {tn} / {fn}"
    got["judge: precision"] = f"{tp / (tp + fp):.1%}"
    got["judge: recall"] = f"{tp / (tp + fn):.1%}"
    got["judge: accuracy"] = f"{(tp + tn) / len(judge):.1%}"

    solver = _load(SOLVER_FILE)
    got["solver: records (scenario x provider)"] = str(len(solver))
    true_rate = []
    for conflict, label in ((True, "true"), (False, "false")):
        rows = [r for r in solver if r["valid_conflict"] is conflict]
        for provider in ("openai", "gemini"):
            sub = [r for r in rows if r["provider"] == provider]
            hits = sum(1 for r in sub if r["accept"])
            got[f"solver dev-match, {label}, {provider}"] = _frac(hits, len(sub))
            if conflict:
                true_rate.append(hits / len(sub))
        if conflict:
            got["solver dev-match, true, floor (reported)"] = f"{min(true_rate):.1%}"
            got["solver dev-match, true, pooled"] = _frac(sum(1 for r in rows if r["accept"]), len(rows))
        got[f"structural validity, {label}"] = _frac(sum(1 for r in rows if r["structurally_valid"]), len(rows))
    invalid = [r for r in solver if not r["structurally_valid"]]
    got["structural failures accepted by judge (1)"] = f"{sum(1 for r in invalid if r['accept'])} of {len(invalid)}"
    return got


def _pfmt(p: float) -> str:
    """Two significant digits, halves rounded up, as the docs quote p-values."""
    d = Decimal(repr(p))
    return "0" if d == 0 else str(d.quantize(Decimal(1).scaleb(d.adjusted() - 1), rounding=ROUND_HALF_UP))


def _mcnemar(b: int, c: int) -> float:
    n = b + c
    return 1.0 if n == 0 else min(1.0, 2 * sum(comb(n, k) for k in range(min(b, c) + 1)) / 2 ** n)


def _pct(k: int, n: int) -> str:
    return f"{k}/{n} = 100%" if k == n else _frac(k, n)


def _csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _fisher(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher exact test on [[a, b], [c, d]]: tables as or less likely than this one."""
    n, row, col = a + b + c + d, a + b, a + c
    prob = lambda x: comb(col, x) * comb(n - col, row - x) / comb(n, row)  # noqa: E731
    observed = prob(a)
    return min(1.0, sum(prob(x) for x in range(max(0, row + col - n), min(row, col) + 1)
                        if prob(x) <= observed * (1 + 1e-7)))


def _hits(v: list[dict]) -> dict[tuple[str, str, str], bool]:
    return {(r["group"], r["id"], r["provider"]): r["outcome"] == "gradeable" and r.get("accept") is True
            for r in v}


def _discordant(v: list[dict]) -> tuple[set, set]:
    """(id, provider) pairs missed by the agent only, and by the single-shot rerun only (all 67)."""
    hit = _hits(v)
    keys = {(r["id"], r["provider"]) for r in v}
    agent_only = {k for k in keys if not hit[("agent", *k)] and hit[("single_shot", *k)]}
    single_only = {k for k in keys if hit[("agent", *k)] and not hit[("single_shot", *k)]}
    return agent_only, single_only


def recompute_failures() -> dict[str, str]:
    got: dict[str, str] = {}
    v = [r for r in _load(S3_UNIFIED) if r["kind"] == "verdict"]
    hit = _hits(v)
    labels = _csv(S3_LABELS)
    agent = [r for r in labels if r["setting"] == "agent"]
    single = [r for r in labels if r["setting"] == "single_shot"]
    per = {p: Counter(r["label"] for r in agent if r["provider"] == p) for p in ("openai", "gemini")}
    total = per["openai"] + per["gemini"]
    got["s3 failures: agent misses openai / gemini / total"] = (
        f"{sum(per['openai'].values())} / {sum(per['gemini'].values())} / {len(agent)}")
    for name, c in (("openai", per["openai"]), ("gemini", per["gemini"]), ("total", total)):
        got[f"s3 failures E3/E2/E1/M1/M5/M4/M3/M2: {name}"] = " / ".join(str(c[k]) for k in CODES)
    got["s3 failures: evaluation side (E)"] = (
        f"{sum(r['label'].startswith('E') for r in agent)}/{len(agent)}")
    e1 = [r for r in agent if r["label"] == "E1"]
    got["s3 failures: E1 also missed by single-shot"] = (
        f"{sum(not hit[('single_shot', r['id'], r['provider'])] for r in e1)}/{len(e1)}")
    m2 = [r for r in agent if r["label"] == "M2"]
    got["s3 failures: M2 on import-only blocks"] = (
        f"{sum(r['block_imports_only'] == 'True' for r in m2)} of {len(m2)}")
    false = Counter(r["label"] for r in agent if r["valid_conflict"] == "False")
    got["s3 failures: false conflicts M2 / M1 / M4"] = (
        f"{false['M2']} / {false['M1']} / {false['M4']} of {sum(false.values())}")
    s = Counter(r["label"] for r in single)
    got["s3 failures: single-shot only M3 / M1 / M6"] = f"{s['M3']} / {s['M1']} / {s['M6']} of {len(single)}"
    agent_only, _ = _discordant(v)
    ao = Counter(r["label"][0] if r["label"].startswith("E") else r["label"]
                 for r in agent if (r["id"], r["provider"]) in agent_only)
    got["s3 failures: agent only E / M2 / M1 / M3 / M4"] = (
        f"{ao['E']} / {ao['M2']} / {ao['M1']} / {ao['M3']} / {ao['M4']} of {len(agent_only)}")

    spot = [r for r in agent if r["spot_check"]]
    agree = lambda rs, col: sum(r["author_label"] == r[col] for r in rs)  # noqa: E731
    r1 = [r for r in spot if r["spot_check_round"] == "1"]  # first round: codebook v1
    r2 = [r for r in spot if r["spot_check_round"] == "2"]
    unseen = [r for r in r2 if r["label_shown_before"] == "False"]
    got["s3 spot check: round 1 / round 2 / round 2 unseen / all"] = (
        f"{agree(r1, 'label_v1')}/{len(r1)} / {agree(r2, 'label')}/{len(r2)} / "
        f"{agree(unseen, 'label')}/{len(unseen)} / {agree(r1, 'label_v1') + agree(r2, 'label')}/{len(spot)}")

    sig = _csv(S3_SIGNALS)
    prov = {m: p for p, m in AGENT_MODEL.items()}
    for p, k, name in (("openai", "searched", "searched"), ("gemini", "probed_environment", "probed")):
        rs = [r for r in sig if prov[r["model"]] == p]
        yes = [hit[("agent", r["id"], p)] for r in rs if r[k] == "True"]
        no = [hit[("agent", r["id"], p)] for r in rs if r[k] != "True"]
        a, c = sum(yes), sum(no)
        got[f"s3 signals: {p} {name}, accepted yes / no, Fisher p"] = (
            f"{a}/{len(yes)} = {a / len(yes):.0%} / {c}/{len(no)} = {c / len(no):.0%}, "
            f"p = {_pfmt(_fisher(a, len(yes) - a, c, len(no) - c))}")
    n = lambda p, k: f"{sum(r[k] == 'True' for r in sig if prov[r['model']] == p)}/67"  # noqa: E731
    got["s3 signals: searched openai / gemini; probed openai / gemini"] = (
        f"{n('openai', 'searched')} / {n('gemini', 'searched')}; "
        f"{n('openai', 'probed_environment')} / {n('gemini', 'probed_environment')}")
    g = [r for r in sig if prov[r["model"]] == "gemini"]
    got["s3 signals: gemini checked before editing / read checker source"] = (
        f"{sum(r['checked_before_editing'] == 'True' for r in g)}/{len(g)} / "
        f"{sum(r['read_checker_source'] == 'True' for r in g)}/{len(g)}")
    return got


def recompute_stage3() -> dict[str, str]:
    got: dict[str, str] = {}
    rows = _load(S3_UNIFIED)
    v = [r for r in rows if r["kind"] == "verdict"]
    agent = _csv(S3_AGENT)
    single = _csv(S3_SINGLE)
    hit = lambda r: r["outcome"] == "gradeable" and r.get("accept") is True  # noqa: E731
    by = {(r["group"], r["id"], r["provider"]): r for r in v}
    a = [r for r in v if r["group"] == "agent"]
    count = lambda rs, o: sum(r["outcome"] == o for r in rs)  # noqa: E731
    got["s3 agent: samples / errors / gradeable / empty"] = (
        f"{len(a)} / {count(a, 'error')} / {count(a, 'gradeable')} / {count(a, 'empty')}")
    got["s3 single-shot rerun: records / errors / empty"] = (
        f"{len(single)} / {sum(r['status'] == 'error' for r in single)} / "
        f"{count([r for r in v if r['group'] == 'single_shot'], 'empty')}")
    got["s3 unified: verdict rows / judge calls"] = f"{len(v)} / {sum(r['judged'] for r in v)}"

    def rs(g, prov, vc, drop=False):
        return [r for r in v if r["group"] == g and r["provider"] == prov and r["valid_conflict"] is vc
                and not (drop and r["id"] == PRESTO)]
    for g in ("agent", "single_shot", "june"):
        for vc, t in ((True, "true"), (False, "false")):
            for prov in ("openai", "gemini"):
                got[f"s3 (1) {g}, {t}, {prov}"] = _frac(sum(map(hit, rs(g, prov, vc))), N_TYPE[vc])
        got[f"s3 (1) without presto, {g}"] = " / ".join(
            _frac(sum(map(hit, rs(g, p, True, True))), 48) for p in ("openai", "gemini"))
    got["s3 (1) lower provider, true: agent / single_shot / june"] = " / ".join(
        f"{min(sum(map(hit, rs(g, p, True))) for p in ('openai', 'gemini')) / 49:.1%}"
        for g in ("agent", "single_shot", "june"))

    def secondary(g, prov):
        counted = [r for r in rs(g, prov, True) if SECONDARY[r["outcome"]] != "exclude"]
        return _frac(sum(SECONDARY[r["outcome"]] == "judge" and r.get("accept") is True
                         for r in counted), len(counted))
    got["s3 (1) secondary: agent openai / agent gemini / june gemini"] = " / ".join(
        (secondary("agent", "openai"), secondary("agent", "gemini"), secondary("june", "gemini")))

    def paired(x, y, prov, drop=False):
        ids = sorted({r["id"] for r in rs(x, prov, True, drop)})
        hx = {i: hit(by[(x, i, prov)]) for i in ids}
        hy = {i: hit(by[(y, i, prov)]) for i in ids}
        both = sum(hx[i] and hy[i] for i in ids)
        ox = sum(hx[i] and not hy[i] for i in ids)
        oy = sum(hy[i] and not hx[i] for i in ids)
        return both, ox, oy, len(ids) - both - ox - oy, _pfmt(_mcnemar(ox, oy))
    for prov in ("openai", "gemini"):
        b, ox, oy, n, p = paired("agent", "single_shot", prov)
        got[f"s3 paired agent vs single_shot, {prov}"] = f"{b} / {ox} / {oy} / {n}, p = {p}"
        b, ox, oy, n, p = paired("agent", "single_shot", prov, True)
        got[f"s3 paired without presto, {prov}"] = f"{b} / {ox} / {oy} / {n}, p = {p}"
    _, ox, oy, _, p = paired("single_shot", "june", "gemini")
    got["s3 model drift single_shot vs june, gemini"] = f"{ox} vs {oy}, p = {p}"
    _, ox, oy, _, p = paired("single_shot", "june", "gemini", True)
    got["s3 model drift without presto, gemini"] = f"{ox} vs {oy}, p = {p}"
    _, ox, oy, _, p = paired("single_shot", "june", "openai")
    got["s3 model drift single_shot vs june, openai"] = f"{ox} vs {oy}, p = {p}"

    frozen = {(r["id"], r["provider"]): r for r in _load(SOLVER_FILE)}
    june = [r for r in v if r["group"] == "june" and r["judged"]]
    same = sum(frozen[(r["id"], r["provider"])]["accept"] == r["accept"] for r in june)
    moved = [abs(frozen[(r["id"], r["provider"])]["accept_score"] - r["accept_score"]) for r in june]
    moved = [d for d in moved if d > 1e-9]
    got["s3 judge drift (june vs frozen June)"] = (
        f"{same}/{len(june)} unchanged; {len(moved)} scores moved, max {max(moved):.1f}")

    n_blocks = {r["id"]: int(r["n_blocks"]) for r in agent}
    for g in ("agent", "single_shot", "june"):
        for prov in ("openai", "gemini"):
            t = [r for r in rs(g, prov, True) if r["structurally_valid"] is not None]
            one = [r for r in t if n_blocks[r["id"]] == 1]
            many = [r for r in t if n_blocks[r["id"]] > 1]
            got[f"s3 (2) {g} {prov}: single / multi"] = (
                f"{_pct(sum(r['structurally_valid'] for r in one), len(one))} / "
                f"{_pct(sum(r['structurally_valid'] for r in many), len(many))}")

    am = {p: [r for r in agent if r["model"] == m] for p, m in AGENT_MODEL.items()}
    sm = {p: [r for r in single if r["provider"] == p] for p in AGENT_MODEL}
    num = lambda rs_, k: [float(r[k]) for r in rs_]  # noqa: E731
    mean = lambda xs: sum(xs) / len(xs)  # noqa: E731
    got["s3 calls per scenario, mean (max): agent openai / gemini"] = " / ".join(
        f"{mean(num(am[p], 'model_calls')):.1f} ({max(num(am[p], 'model_calls')):.0f})" for p in AGENT_MODEL)
    got["s3 calls per scenario, mean (max): single-shot openai / gemini"] = " / ".join(
        f"{mean(num(sm[p], 'model_calls')):.2f} ({max(num(sm[p], 'model_calls')):.0f})" for p in AGENT_MODEL)
    got["s3 call ratio agent / single-shot, rounded: openai / gemini"] = " / ".join(
        f"{mean(num(am[p], 'model_calls')) / mean(num(sm[p], 'model_calls')):.0f}" for p in AGENT_MODEL)
    for p in AGENT_MODEL:
        got[f"s3 tool calls bash/view/replace/check: {p}"] = " / ".join(
            f"{sum(num(am[p], k)):.0f}" for k in ("n_bash", "n_view_file", "n_replace_text", "n_check_java"))
    got["s3 ran check_java at least once: openai / gemini"] = " / ".join(
        f"{sum(float(r['n_check_java']) > 0 for r in am[p])}/{len(am[p])}" for p in AGENT_MODEL)
    got["s3 passed check_java only after failing it: openai / gemini"] = " / ".join(
        str(sum(r["fixed_after_failed_check"] == "True" for r in am[p])) for p in AGENT_MODEL)
    got["s3 limits hit: openai / gemini"] = " / ".join(str(sum(bool(r["limit"]) for r in am[p])) for p in AGENT_MODEL)
    got["s3 tool errors: openai / gemini"] = " / ".join(f"{sum(num(am[p], 'tool_errors')):.0f}" for p in AGENT_MODEL)
    got["s3 working time per sample, mean: openai / gemini"] = " / ".join(
        f"{mean(num(am[p], 'working_time_s')):.1f} s" for p in AGENT_MODEL)
    cost = {p: sum(num(am[p], "cost_usd")) for p in AGENT_MODEL}
    got["s3 agent cost: openai / gemini / total"] = (
        f"${cost['openai']:.2f} / ${cost['gemini']:.2f} / ${cost['openai'] + cost['gemini']:.2f}")
    got["s3 single-shot cost estimate: openai / gemini"] = " / ".join(
        f"${sum(num(sm[p], 'est_cost_usd')):.2f}" for p in AGENT_MODEL)
    got["s3 gate: not extractable / out of block / limits hit"] = (
        f"{count(a, 'not_extractable')}/{len(a)} / {count(a, 'out_of_block')}/{len(a)} / "
        f"{sum(bool(r['limit']) for r in agent)}/{len(agent)}")
    return got


def integrity_problems() -> list[str]:
    """Checks that would otherwise let wrong data pass silently."""
    problems = []
    judge, solver = _load(JUDGE_FILE), _load(SOLVER_FILE)
    for name, rows, key, verdict, score in (
        (JUDGE_FILE.name, judge, ("project", "commit", "tool"), "judge", "score"),
        (SOLVER_FILE.name, solver, ("id", "provider"), "accept", "accept_score"),
    ):
        dups = [k for k, n in Counter(tuple(r[f] for f in key) for r in rows).items() if n > 1]
        if dups:
            problems.append(f"{name}: {len(dups)} duplicate rows, e.g. {dups[0]}")
        off = [r for r in rows
               if abs(r[score] - THRESHOLD) >= BOUNDARY and bool(r[verdict]) != (r[score] >= THRESHOLD)]
        if off:
            problems.append(f"{name}: {len(off)} verdicts disagree with score >= {THRESHOLD}")
    v = [r for r in _load(S3_UNIFIED) if r["kind"] == "verdict"]
    dups = [k for k, n in Counter((r["group"], r["id"], r["provider"]) for r in v).items() if n > 1]
    if dups:
        problems.append(f"{S3_UNIFIED.name}: {len(dups)} duplicate rows, e.g. {dups[0]}")
    off = [r for r in v if r["judged"] and abs(r["accept_score"] - THRESHOLD) >= BOUNDARY
           and bool(r["accept"]) != (r["accept_score"] >= THRESHOLD)]
    if off:
        problems.append(f"{S3_UNIFIED.name}: {len(off)} verdicts disagree with score >= {THRESHOLD}")
    unjudged = [r for r in v if not r["judged"] and r["outcome"] == "gradeable"]
    if unjudged:
        problems.append(f"{S3_UNIFIED.name}: {len(unjudged)} gradeable rows without a verdict")
    # the failure labels must cover exactly the agent misses and the single-shot-only misses
    hit = _hits(v)
    labels = _csv(S3_LABELS)
    misses = {(r["id"], r["provider"]) for r in v if r["group"] == "agent" and not hit[("agent", r["id"], r["provider"])]}
    _, single_only = _discordant(v)
    for setting, want in (("agent", misses), ("single_shot", single_only)):
        have = [(r["id"], r["provider"]) for r in labels if r["setting"] == setting]
        if len(have) != len(set(have)) or set(have) != want:
            problems.append(f"{S3_LABELS.name}: {setting} rows do not match the {setting} misses")
    bad = [r for r in labels if r["label"] not in CODES + ("M6",)]
    if bad:
        problems.append(f"{S3_LABELS.name}: {len(bad)} rows with an unknown code")
    if len({(r["model"], r["id"]) for r in _csv(S3_SIGNALS)}) != 134:
        problems.append(f"{S3_SIGNALS.name}: expected 134 distinct samples")
    return problems


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    problems = integrity_problems()
    for path in (JUDGE_FILE, SOLVER_FILE, S3_UNIFIED, S3_AGENT, S3_SINGLE, S3_LABELS, S3_SIGNALS):
        digest = sha256(path)
        print(f"{path.relative_to(ROOT)}  sha256 {digest[:16]}")
        if digest != SHA256[path.name]:
            problems.append(f"{path.name}: sha256 differs from the committed file")
    for p in problems:
        print(f"INTEGRITY: {p}")
    print()
    got = {**recompute(), **recompute_stage3(), **recompute_failures()}
    expected = {**EXPECTED, **EXPECTED_STAGE3, **EXPECTED_FAILURES}
    width = max(len(k) for k in expected)
    bad = 0
    print(f"{'figure':<{width}}  {'recomputed':<20}  {'reported':<20}")
    for key, want in expected.items():
        have = got.get(key, "(missing)")
        ok = have == want
        bad += not ok
        print(f"{key:<{width}}  {have:<20}  {want:<20}  {'ok' if ok else 'MISMATCH'}")
    print(f"\n{len(expected) - bad}/{len(expected)} figures match; {len(problems)} integrity problems.")
    return 1 if bad or problems else 0


if __name__ == "__main__":
    sys.exit(main())
