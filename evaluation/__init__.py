"""DeepEval evaluation suite for ConflictAgent (Phase 1).

Public metrics:
  - resolution_acceptability_metric() -> GEval        (① semantic developer-match judge)
  - StructuralValidity                -> BaseMetric    (② deterministic structural correctness)

See metrics.py for the design note on why ① and ② inspect different views of a scenario.
"""
from .metrics import (
    RESOLUTION_ACCEPTABILITY_CRITERIA,
    StructuralValidity,
    make_judge_model,
    resolution_acceptability_metric,
)

__all__ = [
    "resolution_acceptability_metric",
    "RESOLUTION_ACCEPTABILITY_CRITERIA",
    "StructuralValidity",
    "make_judge_model",
]
