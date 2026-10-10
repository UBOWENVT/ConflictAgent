"""Sample construction and the structural leak whitelist (no model, no sandbox)."""
from __future__ import annotations

import re

from conftest import REPO
from conflictagent import agent, data, groundtruth, merge, solver, validate
from harness import dataset


def test_population_is_the_fixed_67(samples):
    ids = dataset.scenario_ids()
    assert len(ids) == 67
    assert sum(v for _, v in ids) == 49
    assert list(samples) == [sid for sid, _ in ids]
    assert sum(s.metadata["valid_conflict"] for s in samples.values()) == 49


def test_files_are_exactly_the_four_and_byte_identical(samples):
    """Rebuild every sample independently from the full scenario files and compare."""
    scen = {s.id: s for s in data.load_scenarios(java_only=True)}
    for sid, sample in samples.items():
        s = scen[sid]
        fv = data.load_full_versions(s)
        path = s.file_name
        assert set(sample.files) == {path, f"sides/base/{path}", f"sides/left/{path}",
                                     f"sides/right/{path}"}, sid
        merged, _ = merge.reconstruct_merged(fv["base"], fv["left"], fv["right"])
        t, _ = groundtruth.select_target_block(merged, s.conflict_chunk)
        assert sample.files[path] == agent._annotate_target(merged, t), sid
        for ver in dataset.SIDES:
            assert sample.files[f"sides/{ver}/{path}"] == fv[ver], (sid, ver)
        # relative paths only: the local sandbox must stay inside its temp directory
        assert not any(k.startswith("/") or ".." in k.split("/") for k in sample.files), sid


def test_metadata_is_the_allowlist(samples):
    for sid, sample in samples.items():
        assert set(sample.metadata) == dataset.METADATA_KEYS, sid


def test_target_block_round_trip(samples):
    for sid, sample in samples.items():
        m = sample.metadata
        marked = sample.files[m["conflict_path"]]
        block = dataset.target_block(sample)
        assert marked == m["prefix"] + block + m["suffix"], sid
        assert marked.count(solver.TARGET_TAG) == 1 and solver.TARGET_TAG in block, sid
        assert validate.conflict_blocks(marked)[m["target_idx"]] == block, sid
        assert len(validate.conflict_blocks(marked)) == m["n_blocks"], sid


def test_sides_loader_matches_the_pipeline_loader(samples):
    scen = {s.id: s for s in data.load_scenarios(java_only=True)}
    for sid in samples:
        fv = data.load_full_versions(scen[sid])
        assert dataset.load_sides(scen[sid]) == {v: fv[v] for v in dataset.SIDES}, sid


def test_agent_side_code_never_reads_sample_metadata():
    """The pre-agent step, the tools and the prompt see only the sandbox."""
    for name in ("tools.py", "prompts.py"):
        src = (REPO / "harness" / name).read_text()
        assert not re.search(r"metadata", src), name


def test_compose_passes_nothing_into_the_container():
    compose = (REPO / "harness" / "sandbox" / "compose.yaml").read_text()
    body = "\n".join(l for l in compose.splitlines() if not l.lstrip().startswith("#"))
    for forbidden in ("environment", "env_file", "SAMPLE_METADATA", "volumes", "${"):
        assert forbidden not in body, forbidden
    assert "network_mode: none" in body


def test_build_context_holds_only_the_sandbox_files():
    context = REPO / "harness" / "sandbox"
    shipped = {p.name for p in context.iterdir() if p.name != "__pycache__"}
    assert shipped == {"Dockerfile", "compose.yaml", ".dockerignore", "check_java.py",
                       "validate.py"}
    assert (context / ".dockerignore").read_text().split() == ["*", "!check_java.py",
                                                                "!validate.py"]
