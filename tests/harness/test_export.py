"""Export of Inspect logs into run_eval.py-schema records (the input of the unified scoring)."""
from __future__ import annotations

import glob

from conflictagent import validate
from harness import dataset, export
from mockrun import run_mock, tool_call

# the fields evaluation.dataset.build_solver_testcases reads
CONSUMED = {"kind", "id", "provider", "valid_conflict", "final_resolution", "dev_region"}


def test_developer_regions_match_the_june_complete_set(samples, june_records):
    """expected_output hard check: the developer region the export attaches is byte-identical to
    the one the June Dataset B records were judged against, for every scenario."""
    june = {}
    for r in june_records:
        june.setdefault(r["id"], r["dev_region"])
    dev = export.developer_regions(set(samples))
    assert set(dev) == set(samples) == set(june)
    for sid, (region, status, tgt) in dev.items():
        assert status == "ok", sid
        assert region == june[sid], sid
        assert tgt == samples[sid].metadata["target_idx"], sid


def test_mock_run_round_trip(samples, tmp_path):
    s = samples["simplify@f1f39138"]
    path = s.metadata["conflict_path"]
    left = validate.split_diff3_block(dataset.target_block(s))[0]
    run_mock(s.id, [tool_call("replace_text", path=path, old=dataset.target_block(s), new=left),
                    tool_call("submit", answer="left")], tmp_path)
    logs = glob.glob(str(tmp_path / "*.eval"))
    records = export.export_records(logs)
    assert len(records) == 1
    r = records[0]
    assert CONSUMED <= set(r)
    assert (r["kind"], r["setting"], r["provider"], r["outcome"]) == ("llm", "agent", "mock",
                                                                        "gradeable")
    assert r["final_resolution"] == left.strip("\n").rstrip()
    assert r["final_valid"] is True and r["submitted"] is True and r["limit"] is None


def test_latest_log_wins_for_a_rerun_sample(samples, tmp_path):
    s = samples["junit4@4c8d3ff5"]
    path = s.metadata["conflict_path"]
    run_mock(s.id, [tool_call("submit", answer="nothing")], tmp_path)
    run_mock(s.id, [tool_call("replace_text", path=path, old=dataset.target_block(s),
                              new='\t\treturn "4.11-SNAPSHOT";'),
                    tool_call("submit", answer="left")], tmp_path)
    records = export.export_records(glob.glob(str(tmp_path / "*.eval")))
    assert len(records) == 1 and records[0]["outcome"] == "gradeable"
