"""The LabLens workflow for `adk web` (run from the repo root: `adk web adk_apps`).

In the chat box send JSON such as {"path": "data/reports/source/D02.pdf"}.
Uses the live Gemini key from .env and the normal budget guard and response cache.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from lablens import pipeline  # noqa: E402
from lablens.budget import BudgetGuard  # noqa: E402
from lablens.cache import ResponseCache  # noqa: E402

pipeline.RUNTIME.update(cache=ResponseCache(), guard=BudgetGuard(), caller=None, explain_caller=None)

root_agent = pipeline.workflow
