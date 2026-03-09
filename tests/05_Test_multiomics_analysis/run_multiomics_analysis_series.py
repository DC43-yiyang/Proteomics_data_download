"""Per-series multi-omics annotation runner.

Usage
-----
    uv run python tests/Test_multiomics_analysis/run_multiomics_analysis_series.py

Environment overrides
---------------------
    TARGET_SERIES   single GSE ID or comma-separated list (default: all)
    + all options from geo_agent/skills/multiomics_runner.py
"""

import logging
import os
from pathlib import Path

from geo_agent.skills.multiomics_runner import run_series_mode

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s – %(message)s",
    datefmt="%H:%M:%S",
)

_HERE           = Path(__file__).resolve().parent
_OUTPUT_DIR     = _HERE / "debug_multiomics_analysis"
_STRUCTURED_JSON = _HERE.parent / "04_Test_family_soft_parse" / "debug_family_soft_parse" / "family_soft_structured.json"

# Prefix output files with series ID when a single series is targeted
_target = [s.strip() for s in os.getenv("TARGET_SERIES", "").split(",") if s.strip()]
_output_prefix = f"{_target[0]}_" if len(_target) == 1 else ""

if __name__ == "__main__":
    run_series_mode(
        output_dir=_OUTPUT_DIR,
        structured_json=_STRUCTURED_JSON,
        output_prefix=_output_prefix,
    )
