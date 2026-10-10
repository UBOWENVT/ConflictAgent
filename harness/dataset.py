"""Dataset B scenarios -> Inspect Samples.

The population is fixed: the 67 scenario ids of the frozen June solver eval
(results/solver_eval_20260627_095221.jsonl), 49 true / 18 false conflicts.

Each Sample carries exactly four files, written into the sandbox working directory
(/workspace in Docker), with relative paths so the local sandbox stays in its temp dir:

    <path>                    the reconstructed diff3 conflict file, target block tagged
    sides/base/<path>         common ancestor
    sides/left/<path>         left side
    sides/right/<path>        right side

The conflict file is built exactly as the single-shot pipeline builds it (merge.reconstruct_merged
-> groundtruth.select_target_block -> agent._annotate_target). Only base/left/right are read from
the scenario folder: the developer's resolution (child) is never read here and never enters a
Sample; scoring recomputes the developer region offline. Sample.metadata holds only what the
scorer needs to locate the target block (METADATA_KEYS).
"""
from __future__ import annotations

import hashlib
import json

from inspect_ai.dataset import MemoryDataset, Sample

from conflictagent import agent, config, data, groundtruth, merge, solver, validate

FROZEN_SOLVER_EVAL = config.ROOT / "results" / "solver_eval_20260627_095221.jsonl"
N_SCENARIOS, N_TRUE, N_FALSE = 67, 49, 18
SIDES = ("base", "left", "right")
METADATA_KEYS = frozenset({
    "scenario_id", "valid_conflict", "conflict_path", "n_blocks", "target_idx",
    "prefix", "suffix", "target_block_sha256",
})

# Inspect runs this script before the agent starts. Files only: read-only sides guard against
# accidental edits (scoring never reads them); directories stay writable so cleanup works.
SETUP_SCRIPT = "#!/bin/sh\nset -e\nfind sides -type f -exec chmod a-w {} +\n"


def scenario_ids() -> list[tuple[str, bool]]:
    """The fixed (scenario id, valid_conflict) list, in frozen-file order."""
    seen: dict[str, bool] = {}
    for line in FROZEN_SOLVER_EVAL.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            seen.setdefault(rec["id"], rec["valid_conflict"])
    n_true = sum(1 for v in seen.values() if v is True)
    n_false = sum(1 for v in seen.values() if v is False)
    assert (len(seen), n_true, n_false) == (N_SCENARIOS, N_TRUE, N_FALSE), (len(seen), n_true, n_false)
    return list(seen.items())


def load_sides(s: data.Scenario) -> dict[str, str]:
    """base/left/right only, read exactly as data.load_scenario_files reads them."""
    d = data.scenario_dir(s)
    return {ver: (d / ver).read_text(encoding="utf-8", errors="replace") for ver in SIDES}


def build_sample(s: data.Scenario, sides: dict[str, str]) -> Sample:
    merged, _ = merge.reconstruct_merged(sides["base"], sides["left"], sides["right"])
    blocks = validate.conflict_blocks(merged)
    target_idx, _ = groundtruth.select_target_block(merged, s.conflict_chunk)
    if not (0 <= target_idx < len(blocks)):
        raise ValueError(f"{s.id}: target block not located")
    marked = agent._annotate_target(merged, target_idx)
    start, end = validate.block_spans(merged)[target_idx]
    prefix, suffix = merged[:start], merged[end:]   # merged == prefix + block + suffix
    tagged_block = marked[len(prefix):len(marked) - len(suffix)]
    path = s.file_name
    tag_line = marked.count("\n", 0, marked.index(solver.TARGET_TAG)) + 1
    others = (f" The other {len(blocks) - 1} conflict region(s) in the file are not part of this "
              f"task: leave them exactly as they are.") if len(blocks) > 1 else ""
    return Sample(
        id=s.id,
        input=(f"Resolve the merge conflict tagged {solver.TARGET_TAG} in `{path}` (its <<<<<<< "
               f"line is line {tag_line}).{others} The three versions being merged are at "
               f"`sides/base/{path}`, `sides/left/{path}` and `sides/right/{path}`."),
        files={path: marked, **{f"sides/{ver}/{path}": sides[ver] for ver in SIDES}},
        setup=SETUP_SCRIPT,
        metadata={
            "scenario_id": s.id,
            "valid_conflict": s.valid_conflict,
            "conflict_path": path,
            "n_blocks": len(blocks),
            "target_idx": target_idx,
            "prefix": prefix,
            "suffix": suffix,
            # to tell "never edited" apart from "edited but markers remain"
            "target_block_sha256": hashlib.sha256(tagged_block.encode("utf-8")).hexdigest(),
        },
    )


def build_samples(ids: list[str] | None = None) -> list[Sample]:
    fixed = dict(scenario_ids())
    wanted = list(fixed) if ids is None else list(ids)
    unknown = set(wanted) - set(fixed)
    if unknown:
        raise ValueError(f"not in the fixed Dataset B population: {sorted(unknown)}")
    by_id = {s.id: s for s in data.load_scenarios(java_only=True)}
    samples = []
    for sid in wanted:
        s = by_id[sid]
        assert s.is_java and s.valid_conflict is fixed[sid], sid
        samples.append(build_sample(s, load_sides(s)))
    return samples


def build_dataset(ids: list[str] | None = None) -> MemoryDataset:
    return MemoryDataset(build_samples(ids), name="conflictbench_dataset_b")


def target_block(sample: Sample) -> str:
    """The tagged target block as it appears in the sample's conflict file (tests / mock scripts)."""
    m = sample.metadata
    marked = sample.files[m["conflict_path"]]
    return marked[len(m["prefix"]):len(marked) - len(m["suffix"])]
