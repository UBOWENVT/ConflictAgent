"""Reproduce the single-shot baseline (round 0) with the new solver models.

This is the control arm. One solver call per scenario, no validation, no retry —
mirrors LLM_Experiment/llm_experiment_script.py but with current models. Its
outputs are what the agent loop must beat.

TODO: for each scenario, solver.solve(provider, s) once; record; no loop.
"""

if __name__ == "__main__":
    raise SystemExit("run_baseline: not implemented yet")
