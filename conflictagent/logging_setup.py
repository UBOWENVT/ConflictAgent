"""Logging setup for ConflictAgent entry-point scripts.

One call at the top of a script's main() configures the root logger so that:
  - everything (incl. DEBUG) goes to a structured log file
    (outputs/logs/<tag>_<timestamp>.log) with timestamp + level + module, so a run can be
    grepped later or watched live with `tail -f`;
  - the console (terminal) shows bare messages at INFO, so progress and summary tables look
    exactly like the old print() output (DEBUG detail stays in the file, off the terminal);
  - uncaught exceptions (top-level crashes) are written to the log file with a full traceback,
    not just flashed to the terminal.

Library modules NEVER call this -- they only do `log = logging.getLogger(__name__)` and log;
configuring handlers is the entry point's job (the standard logging discipline).

Usage (in a script's main(), after parsing args, before the work):
    from conflictagent.logging_setup import setup_logging
    log_path = setup_logging(tag="eval_A")
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

from . import config

# file lines:  2026-06-26 14:03:09 WARNING conflictagent.llm | [retry 2/4] ...
_FILE_FMT = logging.Formatter(
    "%(asctime)s %(levelname)-7s %(name)s | %(message)s", "%Y-%m-%d %H:%M:%S")
# console lines: bare message, looks like the old print() output
_CONSOLE_FMT = logging.Formatter("%(message)s")

# third-party loggers that would otherwise flood the DEBUG file with request chatter
_NOISY = ("httpx", "httpcore", "urllib3", "openai", "anthropic", "google", "google_genai")


def setup_logging(tag: str = "run", console_level: int = logging.INFO) -> Path:
    """Configure root logging for one script run; return the log file path.

    The file handler captures DEBUG and up; the console handler shows ``console_level`` and up
    (default INFO) so per-round DEBUG introspection lands in the file without spamming the
    terminal. Idempotent within a process: re-calling replaces the handlers, never duplicates.
    """
    log_dir = config.OUTPUT_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{tag}_{time.strftime('%Y%m%d_%H%M%S')}.log"

    file_h = logging.FileHandler(log_path, encoding="utf-8")
    file_h.setLevel(logging.DEBUG)
    file_h.setFormatter(_FILE_FMT)

    console_h = logging.StreamHandler(sys.stdout)
    console_h.setLevel(console_level)
    console_h.setFormatter(_CONSOLE_FMT)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)            # let records flow; handlers do the level gating
    root.handlers[:] = [file_h, console_h]  # replace, so re-calling doesn't duplicate output

    for name in _NOISY:                     # keep SDK request logs out of our DEBUG file
        logging.getLogger(name).setLevel(logging.WARNING)

    # route uncaught exceptions (top-level crashes) into the log file with a full traceback
    def _excepthook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):     # let Ctrl-C behave normally
            sys.__excepthook__(exc_type, exc, tb)
            return
        logging.getLogger("uncaught").error("uncaught exception", exc_info=(exc_type, exc, tb))
    sys.excepthook = _excepthook

    logging.getLogger(__name__).info("logging to %s", log_path)
    return log_path
