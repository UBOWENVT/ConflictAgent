"""Run the validate-and-repair agent loop over the scenarios.

TODO:
  - load scenarios (start with a 5-scenario smoke test, then Java 106 / full 180)
  - for each: agent.resolve(provider, s); collect per-round records
  - then (outside the loop) judge.judge_equivalent on finalized resolutions
  - dump records to outputs/ for metrics.py
"""

if __name__ == "__main__":
    raise SystemExit("run_agent: not implemented yet")
