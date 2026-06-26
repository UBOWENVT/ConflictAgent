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

from deepeval.test_case import LLMTestCase

from conflictagent import data, pairs


def build_metavalidation_testcases(limit: int | None = None) -> list[LLMTestCase]:
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
