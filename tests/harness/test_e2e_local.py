"""End to end through the real Task in the LOCAL sandbox, driven by a scripted mock model.

The local sandbox runs commands on the host, so it is for mock models only (the Task refuses
anything else there; see test_local_sandbox_refuses_non_mock_models).
"""
from __future__ import annotations

import pytest

from conflictagent import validate
from harness import dataset
from mockrun import run_mock, tool_call, tool_results

RES = '\t\treturn "4.11-SNAPSHOT";'


def _score(sample):
    return sample.scores["conflict_file_scorer"]


def _parts(sample):
    block = dataset.target_block(sample)
    return sample.metadata["conflict_path"], block, validate.split_diff3_block(block)


def test_single_block_with_a_failed_check_then_a_fix(samples, tmp_path):
    s = samples["junit4@4c8d3ff5"]
    path, block, _ = _parts(s)
    script = [
        tool_call("bash", command=f"grep -n 'RESOLVE THIS CONFLICT' {path}"),
        tool_call("view_file", path=path, start=1, end=40),
        tool_call("bash", command=f"diff sides/base/{path} sides/left/{path}; "
                                  f"diff sides/base/{path} sides/right/{path}"),
        tool_call("replace_text", path=f"sides/left/{path}", old="package junit.runner;",
                  new="package x;"),
        tool_call("replace_text", path=path, old=RES.replace("\t", "    "), new=RES),
        tool_call("replace_text", path=path, old=block, new=RES + "\n======="),  # leaves a marker
        tool_call("check_java", path=path),
        tool_call("replace_text", path=path, old=RES + "\n=======", new=RES),
        tool_call("check_java", path=path),
        tool_call("submit", answer="Kept the left side's version string."),
    ]
    sample = run_mock(s.id, script, tmp_path)
    results = tool_results(sample)
    assert [f for f, _, _ in results] == ["bash", "view_file", "bash", "replace_text",
                                          "replace_text", "replace_text", "check_java",
                                          "replace_text", "check_java", "submit"]
    assert "[[RESOLVE THIS CONFLICT]]" in results[0][1]
    assert results[1][1].startswith(f"[{path}: lines 1-")
    assert "read-only" in results[3][2]                        # sides/ cannot be edited
    assert "whitespace is ignored" in results[4][2]            # tabs vs spaces hint
    assert results[6][1].startswith("FAIL") and "stray conflict marker" in results[6][1]
    assert results[8][1].startswith("PASS")

    score = _score(sample)
    assert score.metadata["outcome"] == "gradeable"
    assert score.metadata["extraction"] == "exact"
    assert score.answer == RES
    assert score.metadata["structurally_valid"] is True
    assert score.metadata["final_parses"] is True
    assert score.metadata["submitted"] is True


def test_multi_block_target_is_the_second_block(samples, tmp_path):
    s = samples["simplify@f1f39138"]
    path, block, (left, _, _) = _parts(s)
    script = [
        tool_call("replace_text", path=path, old=block, new=left),
        tool_call("check_java", path=path),
        tool_call("submit", answer="Took the left side."),
    ]
    sample = run_mock(s.id, script, tmp_path)
    check = tool_results(sample)[1][1]
    assert check.startswith("PASS") and "1 other conflict region(s) remain" in check
    score = _score(sample)
    assert score.metadata["outcome"] == "gradeable"
    assert score.answer == left.strip("\n").rstrip()
    assert score.metadata["structurally_valid"] is True
    assert "marker-only" in score.metadata["structural_reason"]
    assert score.metadata["final_has_markers"] is True and score.metadata["final_parses"] is None


def test_resolving_another_block_too_is_out_of_block(samples, tmp_path):
    s = samples["XChange@16f86f72"]
    path, block, (left, _, _) = _parts(s)
    other = validate.conflict_blocks(s.metadata["suffix"])[0]
    script = [
        tool_call("replace_text", path=path, old=block, new=left),
        tool_call("replace_text", path=path, old=other, new=validate.split_diff3_block(other)[2]),
        tool_call("check_java", path=path),
        tool_call("submit", answer="Resolved both."),
    ]
    sample = run_mock(s.id, script, tmp_path)
    check = tool_results(sample)[2][1]
    assert check.startswith("FAIL") and "found 0" in check
    score = _score(sample)
    assert score.metadata["outcome"] == "out_of_block"
    assert score.metadata["region"] == left


def test_message_limit_still_scores_the_file(samples, tmp_path):
    s = samples["junit4@4c8d3ff5"]
    path = s.metadata["conflict_path"]
    script = [tool_call("view_file", path=path, start=1, end=10) for _ in range(12)]
    sample = run_mock(s.id, script, tmp_path, message_limit=8)
    assert sample.limit is not None and sample.limit.type == "message"
    score = _score(sample)
    assert score.metadata["outcome"] == "no_edit"
    assert score.metadata["submitted"] is False


def test_local_sandbox_refuses_non_mock_models(samples, tmp_path):
    """Any model that is not mockllm must not run in the local sandbox. A mock under another
    provider name stands in for a real model."""
    from inspect_ai import eval as inspect_eval
    from inspect_ai.model import get_model, modelapi
    from inspect_ai.model._providers.mockllm import MockLLM
    from harness.task import conflict_resolution

    modelapi(name="pretend")(lambda: MockLLM)
    s = samples["junit4@4c8d3ff5"]
    logs = inspect_eval(conflict_resolution(ids=[s.id], sandbox="local"),
                        model=get_model("pretend/model", custom_outputs=[]),
                        log_dir=str(tmp_path), display="none")
    assert logs[0].status == "error"
    assert "Real models run only in the Docker sandbox" in str(logs[0].samples[0].error.message)


@pytest.mark.parametrize("sid", ["AmazeFileManager@4ee2cdaf"])
def test_view_file_pages_large_files_under_the_output_limit(samples, tmp_path, sid):
    s = samples[sid]
    path = s.metadata["conflict_path"]
    script = [tool_call("view_file", path=path, start=1, end=300),
              tool_call("submit", answer="-")]
    sample = run_mock(s.id, script, tmp_path)
    out = tool_results(sample)[0][1]
    assert len(out.encode("utf-8")) < 16 * 1024
    assert "lines 1-300 of 2862" in out or "continue with start=" in out
