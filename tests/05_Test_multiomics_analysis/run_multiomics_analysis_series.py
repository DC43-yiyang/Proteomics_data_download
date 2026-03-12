"""Per-series multi-omics annotation runner.

After LLM annotation completes, results are persisted to the database.

Usage
-----
    uv run python tests/05_Test_multiomics_analysis/run_multiomics_analysis_series.py

Environment overrides
---------------------
    TARGET_SERIES   single GSE ID or comma-separated list (default: all)
    DB_PATH         SQLite database path (default: data/geo_agent.db)
    + all options from geo_agent/skills/multiomics_runner.py
"""

import json
import logging
import os
from pathlib import Path

from geo_agent.skills.multiomics_runner import run_series_mode

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s – %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

_HERE           = Path(__file__).resolve().parent
_OUTPUT_DIR     = _HERE / "debug_multiomics_analysis"
_STRUCTURED_JSON = _HERE.parent / "04_Test_family_soft_parse" / "debug_family_soft_parse" / "family_soft_structured.json"
_DB_PATH        = Path(os.getenv("DB_PATH", "data/geo_agent.db"))

# Prefix output files with series ID when a single series is targeted
_target = [s.strip() for s in os.getenv("TARGET_SERIES", "").split(",") if s.strip()]
_output_prefix = f"{_target[0]}_" if len(_target) == 1 else ""


def _load_series_context_from_db(db_path: Path) -> dict[str, dict[str, str]]:
    """Load summary and overall_design for each series from the database."""
    if not db_path.exists():
        logger.warning("DB not found at %s, series context will be empty", db_path)
        return {}

    from geo_agent.db import Database, DatabaseRepository

    db = Database(db_path)
    db.open()
    repo = DatabaseRepository(db)

    run_id = repo.get_latest_run_id()
    if run_id is None:
        db.close()
        return {}

    rows = db.conn.execute(
        "SELECT accession, summary, overall_design FROM series WHERE pipeline_run_id = ?",
        (run_id,),
    ).fetchall()
    db.close()

    context: dict[str, dict[str, str]] = {}
    for row in rows:
        r = dict(row)
        if r["summary"] or r["overall_design"]:
            context[r["accession"]] = {
                "summary": r["summary"] or "",
                "overall_design": r["overall_design"] or "",
            }

    logger.info("Loaded series context (summary/overall_design) for %d series from DB", len(context))
    return context


def _persist_results_to_db(output_dir: Path, db_path: Path) -> None:
    """Read the merged series results JSON and persist annotations to DB."""
    from geo_agent.db import Database, DatabaseRepository

    # Find the merged series results JSON (pattern: *_series_results.json)
    # Sort by modification time (newest first) to pick the file from this run,
    # not stale files from previous runs with different model names.
    result_files = sorted(output_dir.glob("*_series_results.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not result_files:
        logger.warning("No *_series_results.json found in %s, skipping DB persistence", output_dir)
        return

    # Use the most recently modified file
    result_file = result_files[0]
    logger.info("Persisting annotations from %s to DB", result_file.name)

    data = json.loads(result_file.read_text(encoding="utf-8"))
    model_name = data.get("model", "unknown")
    results = data.get("results", {})

    if not results:
        logger.warning("No results in %s", result_file)
        return

    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = Database(db_path)
    db.open()
    repo = DatabaseRepository(db)

    run_id = repo.get_latest_run_id()
    if run_id is None:
        from geo_agent.models.query import SearchQuery
        run_id = repo.create_run(SearchQuery(data_type="(local)"))

    saved_series = 0
    saved_samples = 0

    for series_id, result in results.items():
        if result.get("error"):
            continue

        # Ensure the series exists in DB
        db.conn.execute(
            """INSERT OR IGNORE INTO series
               (accession, pipeline_run_id, uid, title, in_search_results)
               VALUES (?,?,'','',1)""",
            (series_id, run_id),
        )
        db.conn.commit()

        # Save series-level annotation
        repo.save_series_annotation(series_id, run_id, model_name, result)
        saved_series += 1

        # Save per-sample annotations
        samples = result.get("samples", [])
        if samples:
            # Ensure samples exist in DB (they may already from step 04)
            for s in samples:
                gsm_id = s.get("gsm_id", "")
                if gsm_id:
                    db.conn.execute(
                        """INSERT OR IGNORE INTO sample
                           (gsm_id, series_accession, pipeline_run_id,
                            sample_title)
                           VALUES (?,?,?,?)""",
                        (gsm_id, series_id, run_id,
                         s.get("sample_title", "")),
                    )
            db.conn.commit()
            repo.save_sample_annotations_batch(series_id, run_id, model_name, samples)
            saved_samples += len([s for s in samples if not s.get("error")])

    # Print DB summary
    ann_count = db.conn.execute(
        "SELECT COUNT(*) FROM series_annotation WHERE pipeline_run_id = ?",
        (run_id,),
    ).fetchone()[0]
    sample_ann_count = db.conn.execute(
        "SELECT COUNT(*) FROM sample_annotation WHERE pipeline_run_id = ?",
        (run_id,),
    ).fetchone()[0]
    layer_count = db.conn.execute(
        """SELECT COUNT(*) FROM annotation_layer al
           JOIN sample_annotation sa ON al.sample_annotation_id = sa.id
           WHERE sa.pipeline_run_id = ?""",
        (run_id,),
    ).fetchone()[0]

    print(f"\n{'=' * 60}")
    print(f"Database summary (run_id={run_id})")
    print(f"{'=' * 60}")
    print(f"  model                : {model_name}")
    print(f"  series saved         : {saved_series}")
    print(f"  samples saved        : {saved_samples}")
    print(f"  series_annotation    : {ann_count}")
    print(f"  sample_annotation    : {sample_ann_count}")
    print(f"  annotation_layer     : {layer_count}")

    # Layer-split summary
    layer_split_rows = db.conn.execute(
        """SELECT series_accession, is_layer_split, biological_sample_count,
                  sample_count, layer_split_ratio
           FROM series_annotation
           WHERE pipeline_run_id = ? AND is_layer_split = 1""",
        (run_id,),
    ).fetchall()
    if layer_split_rows:
        print(f"\n  Layer-split series   : {len(layer_split_rows)}")
        for r in layer_split_rows:
            r = dict(r)
            print(f"    {r['series_accession']}: "
                  f"GSMs={r['sample_count']}, "
                  f"bio_samples={r['biological_sample_count']}, "
                  f"ratio={r['layer_split_ratio']}")

    db.close()
    print(f"\n[ok] Annotations persisted to {db_path}")


if __name__ == "__main__":
    # Load series-level context (summary, overall_design) from DB
    series_context = _load_series_context_from_db(_DB_PATH)

    # Run the LLM annotation (writes JSON/Markdown to output_dir)
    run_series_mode(
        output_dir=_OUTPUT_DIR,
        structured_json=_STRUCTURED_JSON,
        output_prefix=_output_prefix,
        series_context=series_context,
    )

    # Persist results to database
    _persist_results_to_db(_OUTPUT_DIR, _DB_PATH)
