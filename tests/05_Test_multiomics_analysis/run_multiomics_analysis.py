"""Per-sample multi-omics annotation runner.

Usage
-----
    uv run python tests/Test_multiomics_analysis/run_multiomics_analysis.py

Environment overrides
---------------------
    TARGET_SERIES        single GSE ID or comma-separated list (default: all)
    TARGET_SAMPLE_INDEX  comma-separated 0-based indices within each series
                         e.g. "0" = first sample only, "0,1,2" = first three
                         default: all samples
    + all options from geo_agent/skills/multiomics_runner.py
"""

import logging
import os
from pathlib import Path

from geo_agent.skills.multiomics_runner import run_sample_mode

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s – %(message)s",
    datefmt="%H:%M:%S",
)

_HERE            = Path(__file__).resolve().parent
_OUTPUT_DIR      = _HERE / "debug_multiomics_analysis"
_STRUCTURED_JSON = _HERE.parent / "04_Test_family_soft_parse" / "debug_family_soft_parse" / "family_soft_structured.json"

# Prefix output files with series ID when a single series is targeted
_target = [s.strip() for s in os.getenv("TARGET_SERIES", "").split(",") if s.strip()]
_output_prefix = f"{_target[0]}_" if len(_target) == 1 else ""

# Optional sample index filter
_idx_raw = os.getenv("TARGET_SAMPLE_INDEX", "").strip()
_target_sample_indices = (
    [int(i) for i in _idx_raw.split(",") if i.strip().isdigit()]
    if _idx_raw else None
)

if __name__ == "__main__":
    run_sample_mode(
        output_dir=_OUTPUT_DIR,
        structured_json=_STRUCTURED_JSON,
        output_prefix=_output_prefix,
        target_sample_indices=_target_sample_indices,
    )
