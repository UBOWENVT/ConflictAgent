"""Deprecated single-shot baseline entrypoint.

The project originally planned to compare "round 0 single-shot" against the validate-and-retry
loop. Full runs showed modern solver models usually emit syntactically valid code on the first
attempt, so that baseline stopped being the main explanatory comparison.

Use scripts/run_eval.py instead. It computes the current baselines:
pick-left, pick-right, pick-longer, and union.
"""

from __future__ import annotations


def main() -> None:
    raise SystemExit(
        "scripts/run_baseline.py is deprecated. "
        "Use `python scripts/run_eval.py --scheme A --providers openai gemini`; "
        "trivial baselines are computed inside run_eval.py."
    )


if __name__ == "__main__":
    main()
