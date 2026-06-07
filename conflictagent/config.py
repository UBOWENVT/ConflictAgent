"""Central configuration for ConflictAgent.

Model IDs below are the best-known names as of 2026-06. VERIFY the exact API
model-id strings in each provider's dashboard before the first real run — model
ids change and these are not yet confirmed against live APIs.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# --- Repo paths ---
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"                       # gitignored; populated by scripts/fetch_data.py
CONFLICTBENCH_XLSX = DATA_DIR / "ConflictBench.xlsx"
SCENARIOS_DIR = DATA_DIR / "merge_scenarios"   # full files (only needed for local syntax validation)
OUTPUT_DIR = ROOT / "outputs"

# --- ConflictBench source (public repo) ---
CONFLICTBENCH_REPO = "https://github.com/UBOWENVT/ConflictBench"
CONFLICTBENCH_RAW = "https://raw.githubusercontent.com/UBOWENVT/ConflictBench/master"
GOLD_SHEET = "Paper_Textual_Conflict"          # 180 rows, one scenario each

# --- Models (decided 2026-06-06; see SPEC open decision #1) ---
# Two solvers (mirrors the single-shot baseline's two-model setup) + one judge.
# Hard rule: solver != judge (avoid self-preference). TODO: verify exact ids.
SOLVER_MODELS = {
    "openai": "gpt-5.4-2026-03-05",
    "gemini": "gemini-3.5-flash",
}
JUDGE_MODEL = ("anthropic", "claude-sonnet-4-6")  # bump to Opus 4.8 if judge accuracy is short

# --- API keys (from .env; never hard-code) ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# --- Agent loop ---
MAX_RETRIES = 3                  # SPEC open decision #4 (start at 3)
INPUT_GRANULARITY = "region"     # SPEC #2: start region-only; "window" / "file" are fallbacks
WINDOW_LINES = 50                # used only if INPUT_GRANULARITY == "window"

# --- Resolution strategy set (from baseline) ---
N_STRATEGIES = 7
