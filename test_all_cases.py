"""Phase 1 smoke run on all local Family SOFT files.

Usage:
    .venv/bin/python test_all_cases.py
"""

from pathlib import Path

from geo_agent.skills.sample_selector import preprocess_family_soft_directory

INPUT_DIR = Path("debug_family_soft")
OUTPUT_FILE = Path("debug_phase1_context.json")


def main() -> None:
    contexts = preprocess_family_soft_directory(
        input_dir=INPUT_DIR,
        output_file=OUTPUT_FILE,
    )

    total_series = len(contexts)
    total_samples = sum(item["sample_count"] for item in contexts.values())
    with_files = sum(item["samples_with_supp_files"] for item in contexts.values())
    without_files = sum(item["samples_without_supp_files"] for item in contexts.values())

    print("=" * 70)
    print(f"Phase 1 completed: {total_series} series")
    print(f"Total GSM samples: {total_samples}")
    print(f"Samples with supplementary files: {with_files}")
    print(f"Samples without supplementary files: {without_files}")
    print(f"Saved: {OUTPUT_FILE}")
    print("=" * 70)


if __name__ == "__main__":
    main()
