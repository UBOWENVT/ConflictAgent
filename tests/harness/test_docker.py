"""The Docker sandbox: image contents and one mock-model sample end to end inside a container.

    .venv-harness/bin/python -m pytest tests/harness -m docker
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess

import pytest

from conftest import REPO
from harness import dataset
from mockrun import run_mock, tool_call, tool_results

pytestmark = pytest.mark.docker

COMPOSE = REPO / "harness" / "sandbox" / "compose.yaml"
IMAGE = "conflictagent-sandbox:0.1"
RES = '\t\treturn "4.11-SNAPSHOT";'


def _docker(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([shutil.which("docker"), *args], capture_output=True, text=True)


@pytest.fixture(scope="module")
def image():
    r = _docker("compose", "-f", str(COMPOSE), "build")
    assert r.returncode == 0, r.stderr[-2000:]
    return IMAGE


def test_image_holds_no_answers_data_or_secrets(image):
    r = _docker("run", "--rm", "--network", "none", "--user", "root", image, "sh", "-c",
                "find / \\( -path /proc -o -path /sys \\) -prune -o \\( -name child "
                "-o -name '*.xlsx' -o -name '.env' -o -name '*.jsonl' \\) -print")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == ""
    env = _docker("image", "inspect", image, "--format", "{{json .Config.Env}}").stdout
    assert not re.search(r"(API|SECRET|TOKEN|PASSWORD)", env, re.I)


def test_image_runs_as_non_root_with_a_root_owned_checker(image):
    r = _docker("run", "--rm", "--network", "none", image, "sh", "-c",
                "id -u; pwd; test -w /opt/harness/check_java.py && echo writable || echo locked")
    assert r.stdout.split() == ["1000", "/workspace", "locked"]


def test_mock_sample_end_to_end_in_docker(samples, image, tmp_path):
    s = samples["junit4@4c8d3ff5"]
    path = s.metadata["conflict_path"]
    script = [
        tool_call("bash", command="env"),
        tool_call("bash", command="id -u; id -un; pwd"),
        tool_call("bash", command="find /workspace -type f | sort"),
        tool_call("bash", command="python3 -c \"import socket; "
                                  "socket.create_connection(('1.1.1.1', 53), timeout=3)\" 2>&1; "
                                  "echo exit=$?"),
        tool_call("bash", command=f"echo x >> sides/left/{path}; echo exit=$?"),
        tool_call("replace_text", path=path, old=dataset.target_block(s), new=RES),
        tool_call("check_java", path=path),
        tool_call("submit", answer="Kept the left side's version string."),
    ]
    sample = run_mock(s.id, script, tmp_path, sandbox="docker")
    results = tool_results(sample)
    assert [f for f, _, _ in results][-1] == "submit"
    env, ident, files, net, ro, _, check = (out for _, out, _ in results[:7])

    # no credentials and nothing from the host environment
    names = {line.split("=", 1)[0] for line in env.splitlines() if "=" in line}
    leaked = sorted(n for n in names if re.search(r"(API_KEY|SECRET|TOKEN)", n))
    assert not leaked, leaked
    host_keys = sorted(k for k in os.environ if k.endswith("_API_KEY"))
    assert not [k for k in host_keys if k in names]
    assert "/Users/" not in env

    assert ident.split() == ["1000", "agent", "/workspace"]
    assert files.split() == sorted(f"/workspace/{p}" for p in s.files)
    assert "exit=1" in net and "unreachable" in net.lower()
    assert "Permission denied" in ro

    assert check.startswith("PASS")
    score = sample.scores["conflict_file_scorer"]
    assert score.metadata["outcome"] == "gradeable"
    assert score.answer == RES
    assert score.metadata["structurally_valid"] is True
