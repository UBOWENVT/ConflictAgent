# Case Studies

These examples come from the saved evaluation records:

- `outputs/eval/eval_A_complete.jsonl`
- `outputs/eval/eval_B_complete.jsonl`

They are meant as conversation anchors. The eval files store metric outcomes, not full candidate
code, so these case studies focus on what each case demonstrates about the evaluation design. To
turn any item into a code-level walkthrough, use the scenario ID to inspect `data/scenarios/` and
the selected diff3 block.

## How To Read The Fields

- `valid_conflict`: ConflictBench human label. `True` means a genuine conflict; `False` means a
  mechanically resolvable conflict.
- `dev_match`: calibrated judge says the model's resolution is acceptable relative to the
  developer's actual resolution.
- `standalone`: judge says the model's resolution is reasonable from base/left/right alone. This is
  meaningful as a correctness metric only for `valid_conflict=False`.
- `final_valid`: after splicing the candidate into the reconstructed file, the validation layer
  accepts it.
- `dev_status`: whether the developer resolution could be safely extracted from `child`.
- `punt`: scheme B model declares `TRUE_CONFLICT` and does not produce a resolution.

## 1. `dubbo@b7b34b6c`: LLM Beats Trivial Baselines

Why this case is useful: it explains why the project switched from a single-shot baseline to
trivial baselines.

From scheme A:

| Solver / baseline | dev_match | standalone | final_valid | strategy |
| --- | --- | --- | --- | --- |
| OpenAI | True | True | True | L+R |
| Gemini | True | True | True | L+R |
| pick-left | False | True | n/a | n/a |
| pick-right | False | False | n/a | n/a |
| pick-longer | False | True | n/a | n/a |
| union | False | False | n/a | n/a |

Talking point: a simple heuristic can produce something that looks plausible in isolation
(`standalone=True`) but still misses the developer's actual merge intent (`dev_match=False`). Both
LLMs produced an acceptable developer-match resolution here.

## 2. `error-prone@6f83c083`: True Conflict Where Heuristics Fail

Why this case is useful: it shows the main value proposition on genuine conflicts.

From scheme A:

| Solver / baseline | dev_match | standalone | final_valid | strategy |
| --- | --- | --- | --- | --- |
| OpenAI | True | True | True | L+R |
| Gemini | True | True | True | L+R |
| pick-left | False | False | n/a | n/a |
| pick-right | False | False | n/a | n/a |
| pick-longer | False | False | n/a | n/a |
| union | False | False | n/a | n/a |

Talking point: `valid_conflict=True` means this is not just a mechanical keep-both case. The
trivial baselines miss it, while both LLMs produce developer-match resolutions. This is the kind of
case behind the headline that LLMs outperform traditional tools on true conflicts.

## 3. `Matisse@93d0051c`: Scheme B Punt / Detection

Why this case is useful: it explains detection precision and abstention.

From scheme B:

| Solver | valid_conflict | status | punt | dev_match | standalone |
| --- | --- | --- | --- | --- | --- |
| OpenAI | True | punt | True | n/a | n/a |
| Gemini | True | punt | True | n/a | n/a |

Talking point: scheme B allows the model to say "this is a true conflict; do not auto-resolve."
Here both solvers punted, and the human `Valid Conflict` label agrees. That counts as a correct
detection event, not as a resolution. Across the full run, punts were rare but precise.

## 4. `mybatis-3@3502f7ce`: Baseline Can Beat The LLM

Why this case is useful: it prevents overclaiming.

From scheme A:

| Solver / baseline | dev_match | standalone | final_valid | strategy |
| --- | --- | --- | --- | --- |
| OpenAI | False | True | True | L+R |
| Gemini | False | True | True | L+R |
| pick-left | False | True | n/a | n/a |
| pick-right | True | True | n/a | n/a |
| pick-longer | False | True | n/a | n/a |
| union | False | False | n/a | n/a |

Talking point: sometimes the developer really chose one side, and a trivial side-picking baseline
captures that. Both LLMs produced a reasonable merge in isolation, but not the developer-match
answer. This is why the project reports baselines instead of only raw LLM accuracy.

## 5. `RxJava@45c9dc85`: Standalone Is Not Enough

Why this case is useful: it explains the difference between `developer-match`, `standalone`, and
`final_valid`.

From scheme A:

| Solver / baseline | dev_match | standalone | final_valid | strategy |
| --- | --- | --- | --- | --- |
| OpenAI | False | True | False | R |
| Gemini | False | True | True | L+R |
| pick-left | False | True | n/a | n/a |
| pick-right | False | True | n/a | n/a |
| pick-longer | False | True | n/a | n/a |
| union | False | False | n/a | n/a |

Talking point: several candidates look reasonable from the isolated conflict (`standalone=True`),
but they do not match the developer answer. OpenAI also fails final validation after splice
(`final_valid=False`). This is the concrete reason final validation and developer-match are both
needed.

## 6. `proxyee-down@1d9d7f71`: Guarded Ground Truth Extraction

Why this case is useful: it explains `dev_status` and why denominators are smaller than 93.

From scheme A:

| Solver | valid_conflict | dev_status | dev_match | standalone | final_valid |
| --- | --- | --- | --- | --- | --- |
| OpenAI | False | anchor_not_unique | n/a | True | True |
| Gemini | False | anchor_not_unique | n/a | True | True |

Talking point: the agent can produce and validate a resolution, but the evaluation layer refuses to
guess the developer's corresponding region if context anchors are not unique. Those scenarios are
excluded from developer-match denominators. This is a data-integrity guard, not a model failure.

## 7. `cat@1bd24982`: False Conflict Still Can Be Mishandled

Why this case is useful: it explains why false conflicts are not automatically easy.

From scheme A:

| Solver / baseline | valid_conflict | dev_match | standalone | final_valid | strategy |
| --- | --- | --- | --- | --- | --- |
| OpenAI | False | False | False | True | L+R |
| Gemini | False | False | False | True | L+R |
| pick-left | False | True | True | n/a | n/a |
| pick-longer | False | True | True | n/a | n/a |

Talking point: even on `valid_conflict=False`, "keep both sides" is not always correct. The
developer-compatible solution was closer to a side-picking baseline. This is a good example for
explaining why the evaluation separates false conflicts from true conflicts and still compares
against trivial baselines.

## Good Conversation Framing

Use these examples to explain the project in layers:

1. `dubbo` / `error-prone`: LLMs can beat simple heuristics.
2. `Matisse`: punt is a detection event, not a failed resolution.
3. `mybatis-3` / `cat`: baselines are necessary because LLMs can over-merge.
4. `RxJava`: standalone-valid and final-valid answer different questions.
5. `proxyee-down`: denominators are guarded by extraction safety.

The core message is not "LLMs solve every merge conflict." It is: with a clean evaluation harness,
modern LLMs outperform traditional tools on many true conflicts, but the result only becomes
credible because the project also reports baselines, abstention behavior, validation failures, and
ground-truth extraction limits.
