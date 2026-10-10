"""check_java (runs inside the sandbox) vs the single-shot pipeline's validator."""
from __future__ import annotations

import importlib.util
import subprocess
import sys

import pytest

from conftest import REPO
from conflictagent import agent, validate
from harness import dataset

SANDBOX_DIR = REPO / "harness" / "sandbox"


@pytest.fixture(scope="module")
def cj():
    sys.path.insert(0, str(SANDBOX_DIR))
    spec = importlib.util.spec_from_file_location("check_java", SANDBOX_DIR / "check_java.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _edited(sample, resolution: str) -> str:
    m = sample.metadata
    return m["prefix"] + resolution + m["suffix"]


def _left(sample) -> str:
    return validate.split_diff3_block(dataset.target_block(sample))[0]


def test_sandbox_validate_is_a_byte_identical_copy():
    assert (SANDBOX_DIR / "validate.py").read_bytes() == \
        (REPO / "conflictagent" / "validate.py").read_bytes()


def test_unresolved_tag_fails(cj, samples):
    s = samples["junit4@4c8d3ff5"]
    ok, msg = cj.check(s.files[s.metadata["conflict_path"]], 0)
    assert not ok and "not resolved yet" in msg


def test_single_block_resolved_passes_and_stray_marker_fails(cj, samples):
    s = samples["junit4@4c8d3ff5"]
    ok, msg = cj.check(_edited(s, _left(s)), 0)
    assert ok, msg
    ok, msg = cj.check(_edited(s, _left(s) + "\n======="), 0)
    assert not ok and "stray conflict marker" in msg


def test_single_block_parse_error_and_duplicate_declaration(cj, samples):
    s = samples["junit4@4c8d3ff5"]
    ok, msg = cj.check(_edited(s, _left(s) + "\n\t\treturn ;;; }"), 0)
    assert not ok and "does not parse" in msg
    # an over-scoped resolution that re-opens the enclosing method: id() is declared twice
    overscoped = _left(s) + "\n\t}\n\n\tpublic static String id() {\n" + _left(s)
    ok, msg = cj.check(_edited(s, overscoped), 0)
    assert not ok and "duplicate method" in msg


def test_multi_block_other_markers_are_expected(cj, samples):
    s = samples["simplify@f1f39138"]          # 2 blocks, target is the second one
    assert s.metadata["n_blocks"] == 2 and s.metadata["target_idx"] == 1
    ok, msg = cj.check(_edited(s, _left(s)), 1)
    assert ok and "1 other conflict region(s) remain" in msg and "Reference only" in msg


def test_multi_block_tag_removed_but_markers_kept_fails(cj, samples):
    s = samples["simplify@f1f39138"]
    untagged = dataset.target_block(s).replace("   " + cj.TARGET_TAG, "")
    ok, msg = cj.check(_edited(s, untagged), 1)
    assert not ok and "found 2" in msg


def test_multi_block_resolving_another_block_too_fails(cj, samples):
    s = samples["XChange@16f86f72"]           # 2 blocks, target is the first one
    text = _edited(s, _left(s))
    other_s, other_e = validate.block_spans(text)[0]
    text = text[:other_s] + validate.split_diff3_block(text[other_s:other_e])[0] + text[other_e:]
    ok, msg = cj.check(text, 1)
    assert not ok and "found 0" in msg and "resolve ONLY the tagged one" in msg


def test_parity_with_the_pipeline_validator(cj, samples, june_records):
    """Same verdict as agent._validate on realistic candidates: every June resolution, plus the
    plain left / right side of every scenario. Empty candidates are excluded: _validate rejects
    them and check_java cannot see the region (documented difference)."""
    n = 0
    for sample in samples.values():
        cands = list(validate.split_diff3_block(dataset.target_block(sample))[::2])
        cands += [r["final_resolution"] for r in june_records if r["id"] == sample.id]
        m = sample.metadata
        block = dataset.target_block(sample).replace("   " + cj.TARGET_TAG, "")
        merged = m["prefix"] + block + m["suffix"]          # the untagged original
        for cand in cands:
            if not cand.strip():
                continue
            want, _ = agent._validate(cand, merged, m["target_idx"], True)
            got, msg = cj.check(_edited(sample, cand), m["n_blocks"] - 1)
            assert got == want, (sample.id, msg, cand[:200])
            n += 1
    assert n > 250


def test_cli_exit_status(tmp_path, samples):
    s = samples["junit4@4c8d3ff5"]
    f = tmp_path / "Version.java"
    f.write_text(_edited(s, _left(s)), encoding="utf-8")
    run = lambda *a: subprocess.run([sys.executable, str(SANDBOX_DIR / "check_java.py"), *a],  # noqa: E731
                                    capture_output=True, text=True)
    r = run(str(f), "--expect-blocks", "0")
    assert r.returncode == 0 and r.stdout.startswith("PASS")
    f.write_text(s.files[s.metadata["conflict_path"]], encoding="utf-8")
    assert run(str(f)).returncode == 1
    assert run(str(tmp_path / "missing.java")).returncode == 2
