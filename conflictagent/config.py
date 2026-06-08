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

# Deterministic decoding for reproducible evaluation (decided 2026-06-08).
# NOTE: some OpenAI models only accept the default temperature and ERROR on temperature=0.
# If the smoke run fails on the OpenAI call with a temperature error, set this to None
# (llm.call omits the parameter entirely when temperature is None).
LLM_TEMPERATURE: float | None = 0

# --- API keys (from .env; never hard-code) ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# --- Agent loop ---
MAX_RETRIES = 3                  # SPEC open decision #4 (start at 3)

# --- Solver context window (2026-06-08 redirect) ---
# The solver is shown a WINDOW of the file (file skeleton + the minimal complete brace scope
# enclosing the target conflict), not the whole file: RxJava's Observable.java alone was ~103k
# tokens. Files at or under this many lines are shown whole (windowing only helps big files).
WINDOW_FULLFILE_MAX_LINES = 400

# --- Evaluation schemes (2026-06-08; see _HANDOFF.md §6) -----------------------
# Two prompt structures, both run at full scale (A is primary); they are an ablation, not a
# repeat: does forcing the model to declare conflict-ness first change resolution quality?
#   A = fair capability squeeze: NO validity gating. The model always produces a resolution +
#       self-reported strategy + confidence -> desirability covers all scenarios (incl. true
#       conflicts); "detection" becomes confidence calibration (does low confidence track low
#       desirability?).
#   B = classic two-stage: the model first declares TRUE_CONFLICT (punt, no resolution) or
#       RESOLVABLE (then resolves); punt vs the human 'Valid Conflict' label is the Detection
#       metric, directly comparable to the 5 merge tools.
SCHEMES = ("A", "B")
DEFAULT_SCHEME = "A"

# Self-reported resolution strategy vocabulary (matches ConflictBench's Child Resolution Pattern:
# L 62, R 41, L+R 29, L+R+M 17, R+M 3, L+M 2, M 2 over 180 scenarios). Canonical component order
# below is used to normalize free-form model answers.
STRATEGY_COMPONENT_ORDER = ("L", "R", "M")
CONFIDENCE_LEVELS = ("low", "medium", "high")
