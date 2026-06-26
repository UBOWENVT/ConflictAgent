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

Filtering mirrors scripts/calibrate_judge.py exactly, so the population is the same:
  - skip punts (tool left the conflict unresolved -> a detection event, not a resolution);
  - skip empty xlsx-fallback pairs (genuinely-missing snippet, e.g. a deletion).
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
    for lab in labels:
        if lab.is_punt:
            continue  # detection event, not a desirability judgment
        ji = pairs.build_judge_inputs(lab)
        if ji.source == "xlsx" and (not ji.candidate.strip() or not ji.developer.strip()):
            continue  # genuinely-missing xlsx fallback
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
