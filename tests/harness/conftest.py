"""Shared fixtures for the harness tests.

Run with the harness environment from the repository root:

    .venv-harness/bin/python -m pytest tests/harness              # local sandbox + mock model
    .venv-harness/bin/python -m pytest tests/harness -m docker    # Docker sandbox tests only

Everything uses Inspect's mockllm model with scripted tool calls: no API key, no cost.
Needs the ConflictBench data (scripts/fetch_data.py); the June-replay tests also need
outputs/eval/eval_A_complete.jsonl. Missing inputs skip the tests that need them.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from conflictagent import config as ca_config  # noqa: E402

JUNE_COMPLETE_SET = ca_config.OUTPUT_DIR / "eval" / "eval_A_complete.jsonl"


def pytest_configure(config):
    config.addinivalue_line("markers", "docker: needs a running Docker engine")


def pytest_collection_modifyitems(config, items):
    if not docker_available():
        skip = pytest.mark.skip(reason="Docker engine not available")
        for item in items:
            if "docker" in item.keywords:
                item.add_marker(skip)


def docker_available() -> bool:
    docker = shutil.which("docker")
    if docker is None:
        return False
    return subprocess.run([docker, "info"], capture_output=True).returncode == 0


@pytest.fixture(scope="session")
def samples():
    if not ca_config.CONFLICTBENCH_XLSX.exists():
        pytest.skip("ConflictBench data not fetched (scripts/fetch_data.py)")
    from harness import dataset
    return {s.id: s for s in dataset.build_samples()}


@pytest.fixture(scope="session")
def june_records(samples):
    """The 132 June Dataset B records: final_resolution of every (scenario, provider) that the
    frozen solver eval judged, with the frozen (2) verdict and the June validator's final_valid."""
    if not JUNE_COMPLETE_SET.exists():
        pytest.skip(f"{JUNE_COMPLETE_SET} not present")
    frozen = {}
    for line in (REPO / "results" / "solver_eval_20260627_095221.jsonl").read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            frozen[(r["id"], r["provider"])] = r["structurally_valid"]
    out = []
    for line in JUNE_COMPLETE_SET.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        key = (r.get("id"), r.get("provider"))
        if key in frozen:
            out.append({**r, "frozen_structurally_valid": frozen[key]})
    assert len(out) == len(frozen) == 132
    return out

