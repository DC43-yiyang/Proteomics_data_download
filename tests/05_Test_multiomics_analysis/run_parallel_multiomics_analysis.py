"""Parallel multi-omics annotation runner.

Usage
-----
    # Serial mode (default): process one by one, save merged results
    uv run python tests/05_Test_multiomics_analysis/run_parallel_multiomics_analysis.py

    # Parallel mode: process multiple series concurrently, save per-series
    PARALLEL_MODE=1 NUM_WORKERS=4 \
    uv run python tests/05_Test_multiomics_analysis/run_parallel_multiomics_analysis.py

Environment overrides
---------------------
    PARALLEL_MODE     1=parallel (save per-series), 0=serial (save merged); default: 0
    NUM_WORKERS       number of concurrent workers; default: 1
    TARGET_SERIES     comma-separated GSE IDs; default: all
    + all options from geo_agent/skills/multiomics_runner.py

Output structure
----------------
    Serial mode (PARALLEL_MODE=0):
        debug_parallel_online_multicomics_analysis/
        └── {model_slug}_series_results.json          # merged results

    Parallel mode (PARALLEL_MODE=1):
        debug_parallel_online_multicomics_analysis/
        ├── series/
        │   ├── GSE266455/
        │   │   ├── {model_slug}_result.json
        │   │   └── {model_slug}_result_table.md
        │   ├── GSE268991/
        │   │   ├── {model_slug}_result.json
        │   │   └── {model_slug}_result_table.md
        │   └── ...
        └── {model_slug}_series_results.json          # also save merged for convenience
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
_OUTPUT_DIR     = _HERE / "debug_parallel_online_multicomics_analysis"
_STRUCTURED_JSON = _HERE.parent / "04_Test_family_soft_parse" / "debug_family_soft_parse" / "family_soft_structured.json"

# No prefix for batch processing
_output_prefix = ""

if __name__ == "__main__":
    # Print configuration
    parallel_mode = os.getenv("PARALLEL_MODE", "0") == "1"
    num_workers = int(os.getenv("NUM_WORKERS", "1"))
    target_series = os.getenv("TARGET_SERIES", "all")

    print("=" * 70)
    print("Parallel Multi-omics Annotation Runner")
    print("=" * 70)
    print(f"Mode: {'PARALLEL' if parallel_mode else 'SERIAL'}")
    print(f"Workers: {num_workers}")
    print(f"Target series: {target_series}")
    print(f"Output: {_OUTPUT_DIR}")
    print("=" * 70)
    print()

    run_series_mode(
        output_dir=_OUTPUT_DIR,
        structured_json=_STRUCTURED_JSON,
        output_prefix=_output_prefix,
    )
