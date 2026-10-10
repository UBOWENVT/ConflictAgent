"""Helpers to drive the real Task with a scripted mockllm model (no API key, no cost)."""
from __future__ import annotations

from pathlib import Path

MOCK = "mockllm/model"


def tool_call(name: str, **args):
    from inspect_ai.model import ModelOutput, ModelUsage
    out = ModelOutput.for_tool_call(MOCK, name, args)
    # explicit usage: otherwise mockllm counts tokens with a downloaded tiktoken vocabulary
    out.usage = ModelUsage(input_tokens=1000, output_tokens=50, total_tokens=1050)
    return out


def run_mock(sample_id: str, script: list, log_dir: Path, sandbox: str = "local", **task_args):
    """Run one sample through the real Task with a scripted mock model; return its EvalSample."""
    from inspect_ai import eval as inspect_eval
    from inspect_ai.model import get_model
    from harness.task import conflict_resolution

    logs = inspect_eval(
        conflict_resolution(ids=[sample_id], sandbox=sandbox, **task_args),
        model=get_model(MOCK, custom_outputs=script),
        log_dir=str(log_dir), display="none",
    )
    log = logs[0]
    assert log.status == "success", log.error
    assert log.samples and len(log.samples) == 1
    return log.samples[0]


def tool_results(sample) -> list[tuple[str, str, str | None]]:
    """(function, output text, error message) for every tool message, in order."""
    out = []
    for m in sample.messages:
        if m.role == "tool":
            out.append((m.function, m.text, m.error.message if m.error else None))
    return out
