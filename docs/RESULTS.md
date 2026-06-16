# Results

This file records grounded results from the completed 2026-06-09 milestone.

## Judge Calibration

Developer-match judge calibration used ConflictBench's human desirability labels for tool outputs.

- Total labeled tool pairs: 627.
- Desirability judgments: 310.
- Detection events: 253.
- Empty/skipped fallback cases: 64.
- Developer-match judge: accuracy 70.6%, precision 92.9%, recall 55.6%.

Interpretation: the judge is high precision and conservative. A judge `ACCEPTABLE` verdict is
usually trustworthy; rates are likely lower bounds because recall is modest.

## Standalone-Valid Calibration

Standalone-valid is a separate question: whether a candidate is reasonable from base/left/right
alone, without the developer answer.

On a 40-item human-labeled sample:

- false conflicts: accuracy 85%, precision 88.2%;
- true conflicts: not used as a correctness metric because there is no context-free correct answer.

Only false-conflict standalone-valid should be used as a substantive correctness number.

## Full Evaluation

The primary evaluation uses 93 reconstructable Java scenarios, of which about 72 have safe
developer-region extraction for developer-match.

Scheme A:

- OpenAI developer-match: 38/72 = 52.8%.
- Gemini developer-match: 45/72 = 62.5%.
- Strongest trivial baseline: pick-longer, 33/72 = 45.8%.

Scheme B:

- OpenAI developer-match: 40/72 = 55.6%.
- Gemini developer-match: 43/68 = 63.2%.
- Detection: OpenAI rarely punts; Gemini punted 5 times in the full run and all were true conflicts.

## LLMs vs Five Traditional Tools

Using the same target-block developer-match framing:

- true conflicts: LLMs score about 62-66%;
- strongest traditional tool under the human-label view is <=52%;
- false conflicts: LLMs are at least competitive with the strongest tools.

The main advantage on true conflicts comes from traditional tools abstaining or leaving conflicts
unresolved, while the LLMs usually attempt a resolution.

## Key Findings

- Modern solver models usually produce syntactically valid code on the first attempt.
- Retry remains useful as a safety loop, but it is not the headline result.
- Self-reported confidence is not a reliable desirability predictor.
- Scheme A and B have similar aggregate desirability; scheme B's punt behavior is rare but precise.
- Gemini was generally steadier than OpenAI on final validity in the recorded runs.

## Limitations

- The developer-match judge is conservative and may under-credit acceptable alternatives.
- LLM outputs do not have independent human labels, so some judge-style bias cannot be fully ruled out.
- Anchor-based developer extraction excludes cases where the region cannot be safely located.
- `javalang` checks syntax, not full Java compilation.
- Standalone-valid is meaningful only for false conflicts.
