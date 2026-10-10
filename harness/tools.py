"""Agent tools (view_file, replace_text, check_java) and the pre-agent workspace step.

bash is Inspect's built-in. The file tools replace Inspect's text_editor, which rewrites the whole
file on every edit (tabs expanded to spaces) and so turns a correct in-block edit into an
out-of-block change. These read and write raw bytes and touch nothing but the matched text.
view_file pages by line range so its output stays under Inspect's 16 KiB tool-output truncation.

This module never looks at the Sample's answer-side fields: it sees only the sandbox (enforced by
tests/harness/test_dataset.py, which greps this file).
"""
from __future__ import annotations

import posixpath
import re
from collections.abc import Sequence

from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.tool import Tool, ToolError, tool
from inspect_ai.util import sandbox, store

from conflictagent import validate

MAX_VIEW_LINES = 300
MAX_VIEW_BYTES = 12_000          # leaves headroom under the 16 KiB tool-output limit
CONFLICT_FILE_KEY = "harness:conflict_file"   # store: {"path": str, "n_blocks": int}
DOCKER_CHECK_COMMAND = ("python3", "/opt/harness/check_java.py")


# --------------------------------------------------------------------------- #
# Pre-agent step
# --------------------------------------------------------------------------- #

@solver
def prepare_workspace() -> Solver:
    """Before the agent starts: refuse real models outside a container, then find the conflict
    file in the sandbox and record its conflict-block count (check_java needs the original count).
    """
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        if not str(state.model).startswith("mockllm/"):
            in_container = await sandbox().exec(["test", "-f", "/.dockerenv"])
            if not in_container.success:
                raise RuntimeError(
                    "Real models run only in the Docker sandbox; the local sandbox executes the "
                    "model's commands on the host. Use the default sandbox='docker'.")
        found = await sandbox().exec(
            ["find", ".", "-path", "./sides", "-prune", "-o", "-type", "f", "-print"])
        paths = [p.removeprefix("./") for p in found.stdout.splitlines() if p.strip()]
        if not found.success or len(paths) != 1:
            raise RuntimeError(f"expected exactly one file outside sides/, found {paths}")
        text = (await sandbox().read_file(paths[0], text=False)).decode("utf-8")
        store().set(CONFLICT_FILE_KEY,
                    {"path": paths[0], "n_blocks": len(validate.conflict_blocks(text))})
        return state

    return solve


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #

async def _read_bytes(path: str) -> bytes:
    try:
        return await sandbox().read_file(path, text=False)
    except FileNotFoundError:
        raise ToolError(f"No such file: {path}")
    except IsADirectoryError:
        raise ToolError(f"{path} is a directory.")
    except PermissionError:
        raise ToolError(f"Permission denied: {path}")


def _split_lines(text: str) -> list[str]:
    """Lines as `grep -n` numbers them (split on \\n only; no phantom line after a final \\n)."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


@tool
def view_file() -> Tool:
    async def execute(path: str, start: int = 1, end: int | None = None) -> str:
        """View a line range of a text file, with line numbers.

        Shows at most 300 lines (and about 12 KB) per call; call again from where the output
        stops to see more. Find the lines you need with `grep -n` first rather than paging
        through a whole large file.

        Args:
            path: File path, relative to the working directory.
            start: First line to show (1-based).
            end: Last line to show (inclusive). Defaults to start + 299.
        """
        lines = _split_lines((await _read_bytes(path)).decode("utf-8", errors="replace"))
        n = len(lines)
        if n == 0:
            return f"[{path} is empty]"
        start = max(start, 1)
        if start > n:
            raise ToolError(f"start={start} is past the end of {path} ({n} lines).")
        if end is not None and end < start:
            raise ToolError(f"end={end} is before start={start}.")
        last = min(n, start + MAX_VIEW_LINES - 1, end if end is not None else n)

        rows: list[str] = []
        size = 0
        for i in range(start, last + 1):
            row = f"{i:6d}\t{lines[i - 1]}"
            if len(row.encode("utf-8")) > MAX_VIEW_BYTES:   # one enormous line
                head = row.encode("utf-8")[:MAX_VIEW_BYTES // 2].decode("utf-8", errors="ignore")
                row = head + f" ... [line {i} cut: too long to show]"
            if rows and size + len(row.encode("utf-8")) + 1 > MAX_VIEW_BYTES:
                break
            rows.append(row)
            size += len(row.encode("utf-8")) + 1
        shown_to = start + len(rows) - 1
        header = f"[{path}: lines {start}-{shown_to} of {n}]"
        footer = (f"\n[output stops at line {shown_to}; continue with start={shown_to + 1}]"
                  if shown_to < last else "")
        return header + "\n" + "\n".join(rows) + footer

    return execute


def _without_whitespace(s: str) -> str:
    return re.sub(r"\s+", "", s)


@tool(parallel=False)
def replace_text() -> Tool:
    async def execute(path: str, old: str, new: str) -> str:
        """Replace one exact occurrence of `old` with `new` in a file.

        `old` must match the file exactly, including indentation (tabs vs spaces) and line
        breaks, and must occur exactly once: include enough surrounding lines to make it unique.
        Nothing else in the file is changed.

        Args:
            path: File path, relative to the working directory.
            old: The exact text to replace.
            new: The replacement text.
        """
        if old == "":
            raise ToolError("`old` must not be empty.")
        try:
            text = (await _read_bytes(path)).decode("utf-8")
        except UnicodeDecodeError:
            raise ToolError(f"{path} is not UTF-8 text.")
        count = text.count(old)
        if count == 0:
            hint = (" It does match if whitespace is ignored: copy the indentation exactly (the "
                    "file may use tabs)." if _without_whitespace(old) in _without_whitespace(text)
                    else "")
            raise ToolError(f"`old` was not found in {path}.{hint}")
        if count > 1:
            raise ToolError(f"`old` occurs {count} times in {path}; include more surrounding "
                            f"lines so that it occurs exactly once.")
        i = text.index(old)
        try:
            await sandbox().write_file(path, (text[:i] + new + text[i + len(old):]).encode("utf-8"))
        except PermissionError:
            raise ToolError(f"{path} is read-only.")
        first = text.count("\n", 0, i) + 1
        return (f"OK: replaced lines {first}-{first + old.count(chr(10))} of {path} "
                f"with {new.count(chr(10)) + 1} line(s).")

    return execute


def _recorded_blocks(path: str) -> int | None:
    """Original block count, if `path` names the recorded conflict file."""
    rec = store().get(CONFLICT_FILE_KEY)
    if not rec:
        return None
    norm = posixpath.normpath(path)
    if norm == rec["path"] or norm.endswith("/" + rec["path"]):
        return rec["n_blocks"]
    return None


@tool
def check_java(command: Sequence[str] = DOCKER_CHECK_COMMAND, timeout: int = 60) -> Tool:
    async def execute(path: str) -> str:
        """Check the conflict file after editing it.

        Passes when the tagged conflict is fully resolved (none of its conflict markers left,
        any other conflict regions untouched) and, if no other conflict regions remain, the file
        parses as Java with no duplicate declarations. Run it before submitting.

        Args:
            path: Path of the conflict file, relative to the working directory.
        """
        args = [*command, path]
        original = _recorded_blocks(path)
        if original is not None:
            args += ["--expect-blocks", str(original - 1)]
        result = await sandbox().exec(args, timeout=timeout)
        return (result.stdout + result.stderr).strip()

    return execute
