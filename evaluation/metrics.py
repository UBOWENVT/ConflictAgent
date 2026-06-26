"""DeepEval evaluation suite for ConflictAgent — metric definitions.

Two complementary single-turn metrics (Phase 1):

  ① ResolutionAcceptability (GEval) — the calibrated developer-match judge, reimplemented as a
     DeepEval custom LLM-as-judge metric. The criteria mirror conflictagent/judge.py JUDGE_SYSTEM
     (the v2 rubric that calibration settled on): tolerate housekeeping differences, reject
     unresolved markers / logic & value changes / missing functional code / wrong-side choice.

  ② StructuralValidity (BaseMetric, deterministic, no LLM) — reuses conflictagent/validate.py.
     GEval is explicitly bad at structural/exact checks, so structural correctness is a separate
     deterministic metric: no leftover conflict markers, Java parses (javalang), and no
     over-scoped duplicate declarations (the solver-overrun bug).

Design note — the two metrics inspect DIFFERENT views of the same scenario:
  ① compares the resolution REGION (actual_output) against the developer REGION (expected_output);
  ② needs the FULL SPLICED file to run javalang + duplicate-declaration checks.
A single LLMTestCase has one actual_output, so the runner stashes the spliced full file in
test_case.metadata['spliced_file'] (and a language flag), which ② reads. ① ignores metadata.
Both are written as reusable single-resolution scorers so Phase 2 (trajectory eval) can call them
per retry-round without change.
"""
from __future__ import annotations

from deepeval.metrics import GEval, BaseMetric
from deepeval.test_case import LLMTestCase, SingleTurnParams
from deepeval.models import AnthropicModel

from conflictagent import config, validate


# --------------------------------------------------------------------------- #
# Judge model: same model the hand-built judge used (config.JUDGE_MODEL = (provider, model_id)).
# Cross-vendor vs the solvers (avoid self-preference); temperature=0 for determinism.
# AnthropicModel reads ANTHROPIC_API_KEY from the environment.
# --------------------------------------------------------------------------- #
def make_judge_model() -> AnthropicModel:
    return AnthropicModel(model=config.JUDGE_MODEL[1], temperature=0)


# --------------------------------------------------------------------------- #
# ① Resolution Acceptability — GEval semantic judge.
# Criteria lifted from conflictagent/judge.py JUDGE_SYSTEM (calibrated v2 rubric).
# --------------------------------------------------------------------------- #
RESOLUTION_ACCEPTABILITY_CRITERIA = (
    "Decide whether the Actual Output (a candidate merge-conflict resolution) is an ACCEPTABLE "
    "resolution relative to the Expected Output (the developer's actual resolution of the SAME "
    "conflict): would a careful reviewer accept it as resolving the conflict the way the developer "
    "intended — same behavior and same essential content — even if not character-identical? "
    "These differences alone do NOT make it unacceptable: whitespace, indentation, formatting, or "
    "comments; the ordering of imports, fields, or methods; a different but behaviorally equivalent "
    "phrasing of the same logic; a different set of import statements (which imports are present is "
    "housekeeping, not logic), as long as the actual code is consistent. "
    "Treat it as NOT acceptable if the Actual Output: still contains conflict markers "
    "(<<<<<<<, =======, >>>>>>>) or is otherwise an unresolved / partial merge; has different "
    "program logic or behavior; uses different literal values that matter (version numbers, "
    "constants, configuration values); is missing or adds FUNCTIONAL code (statements, methods, "
    "conditions — not imports); or chooses a different side's behavior than the developer did."
)


def resolution_acceptability_metric(threshold: float = 0.5, model: object | None = None) -> GEval:
    """The ① semantic judge as a DeepEval GEval metric.

    test_case fields used: input = the conflict (diff3 + window); actual_output = candidate
    resolution; expected_output = developer resolution. Score is GEval's 0-1; threshold maps to
    a binary accept/reject so results align with the binary human labels.
    """
    return GEval(
        name="Resolution Acceptability",
        criteria=RESOLUTION_ACCEPTABILITY_CRITERIA,
        evaluation_params=[
            SingleTurnParams.INPUT,
            SingleTurnParams.ACTUAL_OUTPUT,
            SingleTurnParams.EXPECTED_OUTPUT,
        ],
        model=model or make_judge_model(),
        threshold=threshold,
    )


# --------------------------------------------------------------------------- #
# ② Structural Validity — deterministic, no LLM. Reuses conflictagent/validate.py.
# --------------------------------------------------------------------------- #
class StructuralValidity(BaseMetric):
    """Deterministic structural correctness of a candidate resolution.

    Checks (binary 1.0 / 0.0):
      - actual_output (the resolution region) has no leftover conflict markers;
      - the spliced full file parses with javalang  [Java only];
      - the spliced full file has no over-scoped duplicate declarations.

    The spliced full file + language come from test_case.metadata, set by the runner:
        metadata = {'spliced_file': <str|None>, 'language': 'java'|<other>}
    For non-Java (or no spliced file), only the marker check applies.
    """

    def __init__(self, threshold: float = 1.0):
        self.threshold = threshold
        self.score = 0.0
        self.success = False
        self.reason = ""
        self.error = None

    def measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        try:
            candidate = test_case.actual_output or ""
            meta = test_case.metadata or {}
            spliced = meta.get("spliced_file")
            language = (meta.get("language") or "").lower()

            # 1) no leftover conflict markers in the resolution itself
            if validate.has_conflict_markers(candidate):
                return self._fail("leftover conflict markers in resolution")

            # 2)/3) full-file checks (Java only, needs the spliced file)
            if language == "java" and spliced is not None:
                ok, err = validate.syntax_valid(spliced)
                if not ok:
                    return self._fail(f"java does not parse: {err}")
                dup, msg = validate.has_duplicate_declarations(spliced)
                if dup:
                    return self._fail(f"over-scoped duplicate declaration: {msg}")

            return self._pass()
        except Exception as e:  # never let a metric crash the run silently
            self.error = str(e)
            raise

    async def a_measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        # purely synchronous work; reuse measure
        return self.measure(test_case, *args, **kwargs)

    def is_successful(self) -> bool:
        return self.success

    def _pass(self) -> float:
        self.score = 1.0
        self.success = self.score >= self.threshold
        self.reason = "no markers; parses; no duplicate declarations"
        return self.score

    def _fail(self, reason: str) -> float:
        self.score = 0.0
        self.success = False
        self.reason = reason
        return self.score

    @property
    def __name__(self):
        return "Structural Validity"
