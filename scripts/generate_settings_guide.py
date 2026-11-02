# scripts/generate_settings_guide.py
"""Regenerate docs/SETTINGS_GUIDE.md from the settings schema."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from garud360.config.settings_schema import guide_markdown  # noqa: E402

(ROOT / "docs").mkdir(exist_ok=True)
(ROOT / "docs" / "SETTINGS_GUIDE.md").write_text(guide_markdown().rstrip() + "\n", encoding="utf-8")
print("Wrote docs/SETTINGS_GUIDE.md")
