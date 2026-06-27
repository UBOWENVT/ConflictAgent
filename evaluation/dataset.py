"""Build DeepEval datasets for the ConflictAgent suite.

Phase 1 provides the META-VALIDATION dataset: the ~310 human-labeled desirability cases turned into
LLMTestCases, so the ① Resolution Acceptability (GEval) judge can be run over them and its verdicts
compared to the human labels (the ③ judge-validation, done in run_suite.py).

Each test case carries the human label and provenance in metadata:
    metadata = {
        "project", "commit", "tool",   # which (scenario, tool) pair
        "source": "file" | "xlsx",     # how the regions were extracted
        "human_desirable": bool,       # the ground-truth human label (for ③)
    }

Filtering (slightly STRICTER than scripts/calibrate_judge.py, which only drops empty xlsx pairs --
this also drops file-source empties so an empty region never reaches the GEval judge):
  - skip punts (tool left the conflict unresolved -> a detection event, not a resolution);
  - skip pairs whose candidate or developer region is empty, regardless of source (an xlsx deletion,
    or a file-source region the anchor extraction lost to a repack/rename) -- not judgeable.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from deepeval.test_case import LLMTestCase

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from conflictagent import config, data, groundtruth, merge, pairs, validate  # noqa: E402

log = logging.getLogger(__name__)


def build_metaevaluation_testcases(limit: int | None = None) -> list[LLMTestCase]:
    """Desirability labels as LLMTestCases: input=conflict, actual=candidate, expected=developer.

    The human label lives in test_case.metadata['human_desirable'] for the ③ comparison in the runner.
    """
    labels = data.load_manual_labels()
    if limit:
        labels = labels[:limit]

    cases: list[LLMTestCase] = []
    # Population lineage for the judge meta-validation set (see docs/RESULTS.md):
    #   627  all (row x tool) pairs with a 0/1 desirability label   [data.load_manual_labels]
    #    |   (1) drop punts            -- a DATA FACT (lab.is_punt): the tool left the conflict
    #    |                               unresolved, i.e. a detection event, not a resolution.
    #    |   (2) drop empty regions    -- a JUDGEABILITY filter: candidate or developer came out
    #    |                               empty, so there is nothing to compare (and GEval rejects
    #    v                               empty actual_output).
    #   303  judgeable cases fed to the GEval judge. 
    for lab in labels:
        if lab.is_punt:
            continue  # (1) data fact: detection event, not a desirability judgment
        ji = pairs.build_judge_inputs(lab)
        if not ji.candidate.strip() or not ji.developer.strip():
            continue  # (2) judgeability: empty region (xlsx deletion, or a file-source region the
            #         anchor lost to a repack/rename) -- nothing to judge; empty actual_output errors GEval
        cases.append(
            LLMTestCase(
                input=ji.conflict,
                actual_output=ji.candidate,
                expected_output=ji.developer,
                metadata={
                    "project": lab.project,
                    "commit": lab.commit,
                    "tool": lab.tool,
                    "source": ji.source,
                    "human_desirable": lab.desirable,
                },
            )
        )
    return cases


def build_solver_testcases(complete_path: Path | None = None) -> list[LLMTestCase]:
    """Dataset B: LLM solver resolutions as LLMTestCases for the ①+② suite.

    Reads the deduplicated complete set (one record per (scenario, provider), each carrying the
    solver's final_resolution + the developer region it was graded against), reconstructs each
    scenario to recover the diff3 conflict block (① INPUT, built exactly as pairs.build_judge_inputs'
    file-source branch: validate.conflict_blocks(merged)[target_idx]) and the spliced full file
    (② input), then emits one LLMTestCase per usable record.

    Emptiness filtering mirrors build_metaevaluation_testcases, on the solver line:
      - skip the _meta provenance header (kind == '_meta');
      - skip empty actual_output  (final_resolution empty: the honest gemini empties, e.g. jedis/jjwt);
      - skip empty expected_output (dev_region empty: the ok+empty-dev_region scenarios, both providers).

    Multi-block degradation: if the spliced file still contains OTHER blocks' conflict markers, a
    whole-file javalang parse is impossible, so metadata['spliced_file'] is left None and ② falls
    back to the marker-only check on the resolution region -- exactly as agent._validate does.
    """
    complete_path = complete_path or (config.OUTPUT_DIR / "eval" / "eval_A_complete.jsonl")

    # scenario reconstruction map (id -> (Scenario, full_versions)); same population as run_eval,
    # because the complete set's solver records carry only id/provider/resolution/dev_region, not
    # the conflict block or the merged file -- those must be rebuilt here.
    scen: dict[str, tuple] = {}
    for s in data.load_scenarios(java_only=True):
        fv = data.load_full_versions(s)
        if fv:
            scen[s.id] = (s, fv)

    cases: list[LLMTestCase] = []
    skipped = {"meta": 0, "empty_actual": 0, "empty_expected": 0, "no_scenario": 0, "no_block": 0}
    for line in complete_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get("kind") == "_meta":
            skipped["meta"] += 1
            continue
        sid, prov = rec.get("id"), rec.get("provider")
        actual = rec.get("final_resolution") or ""
        expected = rec.get("dev_region") or ""
        if not actual.strip():
            skipped["empty_actual"] += 1
            log.debug("skip %s/%s: empty actual_output (final_resolution)", sid, prov)
            continue
        if not expected.strip():
            skipped["empty_expected"] += 1
            log.debug("skip %s/%s: empty expected_output (dev_region)", sid, prov)
            continue
        if sid not in scen:
            skipped["no_scenario"] += 1
            log.debug("skip %s/%s: scenario not reconstructable", sid, prov)
            continue
        s, fv = scen[sid]
        merged, _ = merge.reconstruct_merged(fv["base"], fv["left"], fv["right"])
        blocks = validate.conflict_blocks(merged)
        target_idx, _ = groundtruth.select_target_block(merged, s.conflict_chunk)
        if not (0 <= target_idx < len(blocks)):
            skipped["no_block"] += 1
            log.debug("skip %s/%s: target block not located", sid, prov)
            continue
        conflict = blocks[target_idx]                          # ① INPUT: diff3 block, no tag/window
        spliced = validate.splice_block(merged, actual, target_idx)
        # multi-block files keep OTHER blocks' markers -> can't whole-file parse; ② degrades to a
        # marker-only check on the resolution region (mirrors agent._validate).
        spliced_for_metric = None if validate.has_conflict_markers(spliced) else spliced
        cases.append(
            LLMTestCase(
                input=conflict,
                actual_output=actual,
                expected_output=expected,
                metadata={
                    "id": sid,
                    "provider": prov,
                    "valid_conflict": rec.get("valid_conflict"),
                    "language": "java" if s.is_java else (s.file_type or ""),
                    "spliced_file": spliced_for_metric,
                },
            )
        )
    log.info("Dataset B: %d test cases from %s (skipped: %s)",
             len(cases), complete_path.name, skipped)
    return cases


def _count_table(cases: list[LLMTestCase]) -> None:
    """No-API sanity check: print the Dataset B size stratified by provider and conflict type."""
    from collections import Counter
    by_prov = Counter(c.metadata["provider"] for c in cases)
    by_vc = Counter(c.metadata["valid_conflict"] for c in cases)
    multiblock = sum(1 for c in cases if c.metadata["spliced_file"] is None)
    print(f"Dataset B: {len(cases)} test cases")
    print(f"  by provider      : {dict(by_prov)}")
    print(f"  by valid_conflict: true={by_vc.get(True, 0)}  false={by_vc.get(False, 0)}  "
          f"unknown={by_vc.get(None, 0)}   (true = headline)")
    print(f"  spliced_file=None (multi-block, ② marker-only): {multiblock} / {len(cases)}")


if __name__ == "__main__":
    _count_table(build_solver_testcases())
