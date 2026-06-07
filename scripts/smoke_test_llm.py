"""Smoke test: verify all three LLM providers + model-ids work.

Run:  python scripts/smoke_test_llm.py
Needs: .env filled with all three API keys.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from conflictagent import config, llm  # noqa: E402

TESTS = [
    ("openai",    config.SOLVER_MODELS["openai"]),
    ("gemini",    config.SOLVER_MODELS["gemini"]),
    ("anthropic", config.JUDGE_MODEL[1]),
]


def main() -> None:
    ok = True
    for provider, model in TESTS:
        print(f"  {provider:12s}  {model:30s} ... ", end="", flush=True)
        try:
            resp = llm.call(provider, model, "Reply with exactly: OK", "Hello")
            print(f"got: {resp.strip()[:60]}")
        except Exception as e:
            print(f"FAIL: {e}")
            ok = False
    if ok:
        print("\nAll three providers working. Ready to run baseline / agent.")
    else:
        print("\nSome providers failed — check API keys in .env and model-ids in config.py.")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
