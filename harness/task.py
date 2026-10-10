"""Inspect task: an agent resolves the tagged merge conflict of one ConflictBench scenario per
sample, with shell + file tools, inside a fresh, network-less Docker container.

    inspect eval harness/task.py --model openai/gpt-5.4-2026-03-05
    inspect eval harness/task.py -T ids=junit4@4c8d3ff5,simplify@f1f39138 --model ...

sandbox="local" exists only for mock-model tests: it runs the model's commands on the host, with
the host environment and data/ in reach, so prepare_workspace() refuses any real model there.
"""
from __future__ import annotations

import sys
from pathlib import Path

HARNESS_DIR = Path(__file__).resolve().parent
if str(HARNESS_DIR.parent) not in sys.path:      # `inspect eval harness/task.py` from anywhere
    sys.path.insert(0, str(HARNESS_DIR.parent))

from inspect_ai import Task, task                 # noqa: E402
from inspect_ai.agent import AgentPrompt, AgentSubmit, react   # noqa: E402
from inspect_ai.model import GenerateConfig       # noqa: E402
from inspect_ai.tool import bash                  # noqa: E402

from harness import dataset, prompts, scorers, tools   # noqa: E402

COMPOSE_FILE = HARNESS_DIR / "sandbox" / "compose.yaml"
LOCAL_CHECK_COMMAND = (sys.executable, str(HARNESS_DIR / "sandbox" / "check_java.py"))


def _ids(ids: str | list[str] | None) -> list[str] | None:
    if ids is None or isinstance(ids, list):
        return ids
    return [i.strip() for i in ids.split(",") if i.strip()]


@task
def conflict_resolution(
    ids: str | list[str] | None = None,
    sandbox: str = "docker",
    message_limit: int = 40,
    time_limit: int = 600,
    token_limit: int | None = None,
    tool_timeout: int = 60,
) -> Task:
    if sandbox not in ("docker", "local"):
        raise ValueError(f"sandbox must be 'docker' or 'local', not {sandbox!r}")
    check_command = tools.DOCKER_CHECK_COMMAND if sandbox == "docker" else LOCAL_CHECK_COMMAND
    agent = react(
        prompt=AgentPrompt(instructions=prompts.INSTRUCTIONS, handoff_prompt=None,
                           assistant_prompt=None),
        tools=[
            bash(timeout=tool_timeout),
            tools.view_file(),
            tools.replace_text(),
            tools.check_java(command=check_command, timeout=tool_timeout),
        ],
        # keep the submit call in the transcript: trajectory analysis needs to see it
        submit=AgentSubmit(keep_in_messages=True),
    )
    return Task(
        dataset=dataset.build_dataset(_ids(ids)),
        solver=[tools.prepare_workspace(), agent],
        scorer=scorers.conflict_file_scorer(),
        sandbox=("docker", str(COMPOSE_FILE)) if sandbox == "docker" else "local",
        config=GenerateConfig(temperature=0),
        message_limit=message_limit,
        time_limit=time_limit,
        token_limit=token_limit,
        fail_on_error=0.05,
    )
