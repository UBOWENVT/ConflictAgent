"""Calibrate the LLM-as-judge against ConflictBench's manual labels.

Trust check before the judge is used for headline numbers: run judge.judge_equivalent
on the ~627 (tool resolution, developer, manual desirability 0/1) triples and report
agreement (accuracy / precision / recall vs the human labels). If agreement is high,
the automated judge is defensible; if not, revisit the rubric or bump JUDGE_MODEL.

TODO: data.load_manual_labels() -> run judge on each -> compare to the 0/1 label.
"""

if __name__ == "__main__":
    raise SystemExit("calibrate_judge: not implemented yet")
