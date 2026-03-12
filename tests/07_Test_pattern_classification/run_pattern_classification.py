"""Test 07: Upload Pattern Classification

Classifies all standalone series in the latest pipeline run into upload patterns,
persists results to the series table, and prints a summary.

Run:
    uv run python tests/07_Test_pattern_classification/run_pattern_classification.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

from dotenv import load_dotenv
load_dotenv()

from geo_agent.db.connection import Database
from geo_agent.db.repository import DatabaseRepository

DB_PATH = os.getenv("DB_PATH", "data/geo_agent.db")

EXPECTED_PATTERNS = {
    # Pattern 2: series-level files only
    "GSE266455": "pattern2",
    "GSE267552": "pattern2",
    "GSE283984": "pattern2",
    "GSE291290": "pattern2",
    "GSE294427": "pattern2",
    "GSE309625": "pattern2",
    "GSE313153": "pattern2",
    "GSE316782": "pattern2",
    "GSE320155": "pattern2",
    # Pattern 3 merged
    "GSE207438": "pattern3_merged",
    "GSE268991": "pattern3_merged",
    "GSE299416": "pattern3_merged",
    "GSE303197": "pattern3_merged",
    "GSE303984": "pattern3_merged",
    "GSE306022": "pattern3_merged",
    "GSE313894": "pattern3_merged",
    # Pattern 3 single-omic
    "GSE280852": "pattern3_singleomic",
    "GSE296447": "pattern3_singleomic",
    "GSE299415": "pattern3_singleomic",
    "GSE306608": "pattern3_singleomic",
    "GSE315668": "pattern3_singleomic",
    # Pattern 4: layer-split
    "GSE269123": "pattern4",
    "GSE287976": "pattern4",
    "GSE305370": "pattern4",
    "GSE316069": "pattern4",
    "GSE316096": "pattern4",
}


def main():
    print(f"DB: {DB_PATH}")
    print()

    with Database(DB_PATH) as db:
        repo = DatabaseRepository(db)

        run_id = repo.get_latest_run_id()
        if run_id is None:
            print("[ERROR] No pipeline runs found in DB.")
            sys.exit(1)
        print(f"Pipeline run ID: {run_id}")
        print()

        # ── Classify ──────────────────────────────────────────────
        print("Classifying upload patterns...")
        classifications = repo.classify_upload_patterns(run_id)

        if not classifications:
            print("[ERROR] No standalone series found.")
            sys.exit(1)

        # ── Persist ───────────────────────────────────────────────
        repo.save_upload_patterns(run_id, classifications)
        print(f"Saved {len(classifications)} pattern classification(s) to DB.")
        print()

        # ── Verify from DB ────────────────────────────────────────
        saved = repo.get_upload_patterns(run_id)
        saved_map = {r["accession"]: r["upload_pattern"] for r in saved}

        # ── Print results ─────────────────────────────────────────
        pattern_groups: dict[str, list[str]] = {}
        for r in classifications:
            pattern_groups.setdefault(r["pattern"], []).append(r["accession"])

        for pattern, accessions in sorted(pattern_groups.items()):
            print(f"  {pattern} ({len(accessions)}): {', '.join(sorted(accessions))}")
        print()

        # Detailed table
        print(f"{'Accession':<14} {'Pattern':<22} {'Files':<20} {'Detail'}")
        print("-" * 100)
        for r in sorted(classifications, key=lambda x: x["pattern"]):
            file_info = (f"{r['samples_with_files']}/{r['actual_samples']} samples, "
                         f"{r['series_file_count']} series")
            print(f"  {r['accession']:<12} {r['pattern']:<22} {file_info:<20} {r['detail'][:60]}")
        print()

        # ── Assertions ────────────────────────────────────────────
        print("Running assertions against expected patterns...")
        failures = []
        for accession, expected in EXPECTED_PATTERNS.items():
            actual = saved_map.get(accession)
            if actual != expected:
                failures.append(
                    f"  {accession}: expected={expected}, got={actual}"
                )

        if failures:
            print(f"[FAIL] {len(failures)} assertion(s) failed:")
            for f in failures:
                print(f)
            sys.exit(1)

        print(f"[ok] all {len(EXPECTED_PATTERNS)} expected patterns match")
        print()

        # ── Summary ───────────────────────────────────────────────
        counts = {}
        for r in classifications:
            counts[r["pattern"]] = counts.get(r["pattern"], 0) + 1
        print("Summary:")
        for pattern, count in sorted(counts.items()):
            print(f"  {pattern}: {count}")
        print()
        print(f"Total standalone series classified: {len(classifications)}")
        print("Done.")


if __name__ == "__main__":
    main()
