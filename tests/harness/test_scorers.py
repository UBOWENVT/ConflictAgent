"""Extraction, outcome rules and (2) structural validity (pure functions, no sandbox)."""
from __future__ import annotations

from conflictagent import validate
from harness import dataset
from harness.scorers import (OUTCOME_RULES, Extraction, classify_outcome, clean_region,
                             extract_region, structural_validity)

RES = '\t\treturn "4.11-SNAPSHOT";'


def _parts(sample):
    m = sample.metadata
    return m["prefix"], m["suffix"]


def test_exact_extraction(samples):
    pre, suf = _parts(samples["junit4@4c8d3ff5"])
    assert extract_region(pre + RES + suf, pre, suf) == Extraction("exact", RES)
    assert extract_region(pre + "\n" + RES + "\n" + suf, pre, suf) == \
        Extraction("exact", "\n" + RES + "\n")
    assert clean_region("\n" + RES + "  \n") == RES


def test_deleted_block_is_an_empty_exact_region(samples):
    pre, suf = _parts(samples["junit4@4c8d3ff5"])
    assert extract_region(pre + suf, pre, suf) == Extraction("exact", "")
    assert extract_region(pre + suf[1:], pre, suf) == Extraction("exact", "")


def test_whitespace_only_changes_outside(samples):
    """What Inspect's text_editor does: tabs expanded everywhere, plus a lost final newline."""
    pre, suf = _parts(samples["junit4@4c8d3ff5"])
    assert "\t" in pre
    final = (pre + RES + suf).expandtabs(4).rstrip("\n")
    ext = extract_region(final, pre, suf)
    assert ext.status == "whitespace_only"
    assert ext.region == RES.expandtabs(4)
    crlf = (pre + RES + suf).replace("\n", "\r\n")
    assert extract_region(crlf, pre, suf).status == "whitespace_only"


def test_out_of_block_edit_still_locates_the_region(samples):
    pre, suf = _parts(samples["junit4@4c8d3ff5"])
    final = pre.replace("public class Version", "public final class Version") + RES + suf
    ext = extract_region(final, pre, suf)
    assert ext == Extraction("out_of_block", RES)


def test_other_block_resolved_is_out_of_block(samples):
    s = samples["XChange@16f86f72"]                       # target = first of two blocks
    pre, suf = _parts(s)
    left = validate.split_diff3_block(dataset.target_block(s))[0]
    other = validate.conflict_blocks(suf)[0]
    final = pre + left + suf.replace(other, validate.split_diff3_block(other)[2])
    ext = extract_region(final, pre, suf)
    assert ext == Extraction("out_of_block", left)


def test_not_extractable():
    assert extract_region(None, "a\n", "\nb").status == "not_extractable"
    pre = "".join(f"line {i}\n" for i in range(50))
    suf = "".join(f"\nafter {i}" for i in range(50))
    assert extract_region("completely\nrewritten\n", pre, suf).status == "not_extractable"


def test_outcomes():
    ok = Extraction("exact", RES)
    assert classify_outcome(ok, unchanged=False, submitted=True) == "gradeable"
    assert classify_outcome(Extraction("whitespace_only", RES), False, True) == "gradeable"
    assert classify_outcome(Extraction("exact", "<<<<<<< left\nx"), True, False) == "no_edit"
    assert classify_outcome(Extraction("exact", "  \n"), False, True) == "empty"
    marked = Extraction("exact", RES + "\n=======")
    assert classify_outcome(marked, False, True) == "markers"
    assert classify_outcome(marked, False, False) == "unfinished"
    assert classify_outcome(Extraction("out_of_block", RES), False, True) == "out_of_block"
    assert classify_outcome(Extraction("not_extractable", None), False, True) == "not_extractable"


def test_outcome_rules_table():
    """Section 4.5: only a clean in-block resolution reaches the judge under the primary rule."""
    assert {o for o, (p, _) in OUTCOME_RULES.items() if p == "judge"} == {"gradeable"}
    assert OUTCOME_RULES["markers"] == ("miss", "miss")
    assert OUTCOME_RULES["out_of_block"] == ("miss", "judge")
    for o in ("empty", "no_edit", "unfinished", "not_extractable"):
        assert OUTCOME_RULES[o] == ("miss", "exclude")


def test_structural_validity_replays_the_june_verdicts(samples, june_records):
    """(2) on the 132 June resolutions, spliced exactly as Dataset B does, must reproduce the
    frozen verdicts one for one."""
    mismatches = []
    for r in june_records:
        pre, suf = _parts(samples[r["id"]])
        got, reason = structural_validity(clean_region(r["final_resolution"]), pre, suf)
        if got != r["frozen_structurally_valid"]:
            mismatches.append((r["id"], r["provider"], reason))
    assert not mismatches
    assert sum(1 for r in june_records if not r["frozen_structurally_valid"]) == 5
