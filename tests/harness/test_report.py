"""Counting rules of harness/report.py on synthetic verdict rows."""
from __future__ import annotations

from harness.report import mcnemar_exact, paired, primary_hit, secondary, table


def row(group, sid, outcome, accept, vc=True, prov="openai"):
    return {"group": group, "id": sid, "provider": prov, "valid_conflict": vc,
            "outcome": outcome, "judged": accept is not None, "accept": accept,
            "structurally_valid": True}


def test_primary_and_secondary_conventions():
    assert primary_hit(row("a", "x", "gradeable", True))
    assert not primary_hit(row("a", "x", "out_of_block", True))     # primary: always a miss
    assert secondary(row("a", "x", "out_of_block", True)) is True    # secondary: judged in-block
    assert secondary(row("a", "x", "markers", None)) is False
    assert secondary(row("a", "x", "empty", None)) is None           # excluded
    assert secondary(row("a", "x", "error", None)) is None


def test_fixed_denominators():
    rows = [row("a", f"s{i}", "gradeable", True) for i in range(10)]
    rows += [row("a", "e", "empty", None)]
    t = "\n".join(table(rows, ["a"]))
    assert "10/49 = 20.4%" in t          # primary over all 49 true conflicts
    assert "10/10 = 100.0%" in t         # secondary drops the empty one and never-run ones


def test_mcnemar_exact():
    assert mcnemar_exact(0, 0) == 1.0
    assert abs(mcnemar_exact(0, 6) - 0.03125) < 1e-12      # 2 * 0.5**6
    assert abs(mcnemar_exact(3, 3) - 1.0) < 1e-12


def test_paired_counts():
    rows = [row("a", "s1", "gradeable", True), row("b", "s1", "gradeable", False),
            row("a", "s2", "gradeable", False), row("b", "s2", "gradeable", True),
            row("a", "s3", "gradeable", True), row("b", "s3", "gradeable", True)]
    line = paired(rows, "a", "b")[2]
    assert line.startswith("| openai | 1 | 1 | 1 | 0 |")


def test_verify_numbers_matches_the_scoring_rules_and_passes():
    """scripts/verify_numbers.py recomputes the stage-3 figures with the standard library only, so it
    carries its own copy of the secondary convention; it must match OUTCOME_RULES."""
    import importlib.util
    import subprocess
    import sys
    from pathlib import Path

    from harness.scorers import OUTCOME_RULES

    path = Path(__file__).resolve().parents[2] / "scripts" / "verify_numbers.py"
    spec = importlib.util.spec_from_file_location("verify_numbers", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.SECONDARY == {k: v[1] for k, v in OUTCOME_RULES.items()}
    assert subprocess.run([sys.executable, str(path)], capture_output=True).returncode == 0


def test_pfmt_rounds_half_up():
    from harness.report import pfmt
    assert [pfmt(p) for p in (0.0625, 0.625, 0.03125, 0.581, 1.0)] == ["0.063", "0.63", "0.031", "0.58", "1.0"]
