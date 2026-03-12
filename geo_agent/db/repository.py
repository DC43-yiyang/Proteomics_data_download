"""Database repository -- all CRUD operations for the GEO Agent pipeline."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any, Optional

from geo_agent.db.connection import Database

logger = logging.getLogger(__name__)


class DatabaseRepository:
    """Encapsulates all database read/write operations.

    Skills call these methods rather than writing SQL directly.
    """

    def __init__(self, db: Database):
        self._db = db

    @property
    def conn(self) -> sqlite3.Connection:
        return self._db.conn

    # ── Pipeline Run ─────────────────────────────────────────────

    def create_run(self, query: Any) -> int:
        """Insert a new pipeline_run row. Returns the run ID."""
        cur = self.conn.execute(
            """INSERT INTO pipeline_run
               (data_type, organism, disease, tissue, max_results)
               VALUES (?, ?, ?, ?, ?)""",
            (query.data_type,
             getattr(query, "organism", None),
             getattr(query, "disease", None),
             getattr(query, "tissue", None),
             getattr(query, "max_results", 100)),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_latest_run_id(self) -> Optional[int]:
        """Return the most recent pipeline_run ID, or None if no runs exist."""
        row = self.conn.execute(
            "SELECT MAX(id) FROM pipeline_run"
        ).fetchone()
        return row[0] if row and row[0] is not None else None

    def finish_run(self, run_id: int, total_found: int,
                   status: str = "completed") -> None:
        """Mark a pipeline run as finished."""
        self.conn.execute(
            """UPDATE pipeline_run
               SET finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                   total_found = ?, status = ?
               WHERE id = ?""",
            (total_found, status, run_id),
        )
        self.conn.commit()

    # ── Series (Step 01: GEOSearchSkill) ─────────────────────────

    def save_series_batch(self, datasets: list, run_id: int) -> None:
        """Bulk insert GEODataset objects from search results."""
        for ds in datasets:
            self.conn.execute(
                """INSERT OR REPLACE INTO series
                   (accession, pipeline_run_id, uid, title, summary,
                    organism, platform, series_type, sample_count,
                    overall_design, ftp_link, relevance_score,
                    is_valid, validation_notes, in_search_results)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)""",
                (ds.accession, run_id, ds.uid, ds.title, ds.summary,
                 ds.organism, ds.platform, ds.series_type, ds.sample_count,
                 ds.overall_design, ds.ftp_link, ds.relevance_score,
                 int(ds.is_valid), ds.validation_notes),
            )
            for sf in ds.supplementary_files:
                self.conn.execute(
                    """INSERT INTO series_supplementary_file
                       (series_accession, pipeline_run_id, name, url, size_bytes)
                       VALUES (?,?,?,?,?)""",
                    (ds.accession, run_id, sf.name, sf.url, sf.size_bytes),
                )
            for rel in ds.relations:
                self.conn.execute(
                    """INSERT INTO series_relation
                       (series_accession, pipeline_run_id, relation_text)
                       VALUES (?,?,?)""",
                    (ds.accession, run_id, rel),
                )
        self.conn.commit()

    def save_series_soft_text(self, accession: str, run_id: int,
                              soft_text: str) -> None:
        """Store raw SOFT text for a series."""
        self.conn.execute(
            """INSERT OR REPLACE INTO series_soft_text
               (series_accession, pipeline_run_id, soft_text)
               VALUES (?,?,?)""",
            (accession, run_id, soft_text),
        )
        self.conn.commit()

    def get_series_for_run(self, run_id: int) -> list[dict[str, Any]]:
        """Retrieve all series for a pipeline run."""
        rows = self.conn.execute(
            "SELECT * FROM series WHERE pipeline_run_id = ?", (run_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_series_relations(self, accession: str,
                             run_id: int) -> list[str]:
        """Get relation strings for a series."""
        rows = self.conn.execute(
            """SELECT relation_text FROM series_relation
               WHERE series_accession = ? AND pipeline_run_id = ?""",
            (accession, run_id),
        ).fetchall()
        return [r["relation_text"] for r in rows]

    def get_series_soft_text(self, accession: str,
                             run_id: int) -> Optional[str]:
        """Retrieve stored SOFT text for a series."""
        row = self.conn.execute(
            """SELECT soft_text FROM series_soft_text
               WHERE series_accession = ? AND pipeline_run_id = ?""",
            (accession, run_id),
        ).fetchone()
        return row["soft_text"] if row else None

    # ── Hierarchy (Step 02: HierarchySkill) ──────────────────────

    def update_hierarchy(self, accession: str, run_id: int,
                         role: str, parent_accession: Optional[str],
                         in_search_results: bool) -> None:
        """Update hierarchy classification for a series."""
        self.conn.execute(
            """UPDATE series
               SET hierarchy_role = ?, parent_accession = ?,
                   in_search_results = ?
               WHERE accession = ? AND pipeline_run_id = ?""",
            (role, parent_accession, int(in_search_results),
             accession, run_id),
        )
        self.conn.commit()

    def upsert_external_series(self, accession: str, run_id: int,
                               title: str, role: str,
                               parent_accession: Optional[str]) -> None:
        """Insert a series discovered via relations (not in search results)."""
        self.conn.execute(
            """INSERT OR IGNORE INTO series
               (accession, pipeline_run_id, uid, title,
                hierarchy_role, parent_accession, in_search_results)
               VALUES (?,?,'',?,?,?,0)""",
            (accession, run_id, title, role, parent_accession),
        )
        self.conn.commit()

    # ── Samples (Step 04: FamilySoftStructurerSkill) ─────────────

    def replace_series_supplementary_files(
        self, series_accession: str, run_id: int,
        files: list[dict[str, str]],
    ) -> None:
        """Replace series supplementary file records with SOFT-parsed data.

        Deletes existing (potentially inaccurate) records from the esummary
        stage and inserts the correct per-file records from Family SOFT parsing.
        """
        self.conn.execute(
            "DELETE FROM series_supplementary_file "
            "WHERE series_accession = ? AND pipeline_run_id = ?",
            (series_accession, run_id),
        )
        for f in files:
            self.conn.execute(
                """INSERT INTO series_supplementary_file
                   (series_accession, pipeline_run_id, name, url, size_bytes)
                   VALUES (?,?,?,?,?)""",
                (series_accession, run_id, f["file_name"], f["url"], None),
            )
        self.conn.commit()

    def save_samples_batch(self, series_accession: str, run_id: int,
                           samples: list[dict[str, Any]]) -> None:
        """Bulk insert parsed sample records from Family SOFT."""
        for s in samples:
            gsm_id = s["gsm_id"]
            self.conn.execute(
                """INSERT OR REPLACE INTO sample
                   (gsm_id, series_accession, pipeline_run_id,
                    sample_geo_accession, sample_title, sample_status,
                    organism, source_name, library_strategy,
                    library_source, molecule, platform_id,
                    description, library_type)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (gsm_id, series_accession, run_id,
                 s.get("sample_geo_accession", gsm_id),
                 s.get("sample_title", ""),
                 s.get("sample_status", ""),
                 s.get("organism", ""),
                 s.get("source_name", ""),
                 s.get("library_strategy", ""),
                 s.get("library_source", ""),
                 s.get("molecule", ""),
                 s.get("platform_id", ""),
                 s.get("description", ""),
                 s.get("library_type", "")),
            )
            # Characteristics (EAV)
            chars = s.get("characteristics", {})
            raw_rows = s.get("characteristics_rows", [])
            raw_map: dict[str, list[str]] = {}
            for raw in raw_rows:
                if ": " in raw:
                    k, _, _ = raw.partition(": ")
                    raw_map.setdefault(k.strip().lower(), []).append(raw)
            for key, value in chars.items():
                raw_row = raw_map.get(key, [""])[0] if raw_map.get(key) else ""
                self.conn.execute(
                    """INSERT INTO sample_characteristic
                       (gsm_id, series_accession, pipeline_run_id,
                        char_key, char_value, raw_row)
                       VALUES (?,?,?,?,?,?)""",
                    (gsm_id, series_accession, run_id, key, value, raw_row),
                )
            # Supplementary files
            sup_files = s.get("supplementary_files", [])
            sup_names = s.get("supplementary_file_names", [])
            for i, url in enumerate(sup_files):
                name = sup_names[i] if i < len(sup_names) else ""
                self.conn.execute(
                    """INSERT INTO sample_supplementary_file
                       (gsm_id, series_accession, pipeline_run_id,
                        url, file_name)
                       VALUES (?,?,?,?,?)""",
                    (gsm_id, series_accession, run_id, url, name),
                )
            # Relations
            for rel_type in ("sra", "biosample", "other"):
                for url in s.get(f"relation_{rel_type}", []):
                    self.conn.execute(
                        """INSERT INTO sample_relation
                           (gsm_id, series_accession, pipeline_run_id,
                            relation_type, relation_url)
                           VALUES (?,?,?,?,?)""",
                        (gsm_id, series_accession, run_id, rel_type, url),
                    )
            # Notes
            for note in s.get("notes", []):
                self.conn.execute(
                    """INSERT INTO sample_note
                       (gsm_id, series_accession, pipeline_run_id, note)
                       VALUES (?,?,?,?)""",
                    (gsm_id, series_accession, run_id, note),
                )
        self.conn.commit()

    def get_samples_for_series(self, series_accession: str,
                               run_id: int) -> list[dict[str, Any]]:
        """Retrieve all samples for a series, including characteristics."""
        rows = self.conn.execute(
            """SELECT * FROM sample
               WHERE series_accession = ? AND pipeline_run_id = ?""",
            (series_accession, run_id),
        ).fetchall()
        results = []
        for row in rows:
            d = dict(row)
            gsm_id = d["gsm_id"]
            chars_rows = self.conn.execute(
                """SELECT char_key, char_value FROM sample_characteristic
                   WHERE gsm_id = ? AND series_accession = ?
                   AND pipeline_run_id = ?""",
                (gsm_id, series_accession, run_id),
            ).fetchall()
            d["characteristics"] = {r["char_key"]: r["char_value"]
                                    for r in chars_rows}
            results.append(d)
        return results

    # ── Annotations (Step 05: Multiomics*Skill) ──────────────────

    def save_series_annotation(self, series_accession: str, run_id: int,
                               model_name: str,
                               annotation: dict[str, Any]) -> None:
        """Insert per-series LLM annotation."""
        self.conn.execute(
            """INSERT OR REPLACE INTO series_annotation
               (series_accession, pipeline_run_id, model_name,
                disease_normalized, tissue_normalized,
                sample_count, reasoning,
                is_layer_split, biological_sample_count, layer_split_ratio)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (series_accession, run_id, model_name,
             annotation.get("disease_normalized", ""),
             annotation.get("tissue_normalized", ""),
             annotation.get("sample_count", 0),
             annotation.get("reasoning", ""),
             int(annotation["is_layer_split"]) if annotation.get("is_layer_split") is not None else None,
             annotation.get("biological_sample_count"),
             annotation.get("layer_split_ratio", "")),
        )
        self.conn.commit()

    def save_sample_annotations_batch(
        self, series_accession: str, run_id: int,
        model_name: str,
        annotations: list[dict[str, Any]],
    ) -> None:
        """Bulk insert per-sample LLM annotations."""
        for ann in annotations:
            if ann.get("error"):
                continue
            cur = self.conn.execute(
                """INSERT OR REPLACE INTO sample_annotation
                   (gsm_id, series_accession, pipeline_run_id,
                    model_name, sample_title, platform, experiment,
                    assay, disease, tissue, tissue_subtype,
                    confidence, evidence, in_input)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (ann.get("gsm_id", ""), series_accession, run_id,
                 model_name,
                 ann.get("sample_title", ""),
                 ann.get("platform", ""),
                 ann.get("experiment", ""),
                 ann.get("assay", ""),
                 ann.get("disease", ""),
                 ann.get("tissue", ""),
                 ann.get("tissue_subtype", ""),
                 ann.get("confidence", 0.0),
                 ann.get("evidence", ""),
                 ann.get("in_input")),
            )
            ann_id = cur.lastrowid
            for layer in ann.get("measured_layers", []):
                self.conn.execute(
                    """INSERT INTO annotation_layer
                       (sample_annotation_id, layer)
                       VALUES (?,?)""",
                    (ann_id, layer),
                )
        self.conn.commit()

    # ── Pattern Classification (Step 06) ─────────────────────────

    def classify_upload_patterns(self, run_id: int) -> list[dict]:
        """Classify upload pattern for all standalone series in a pipeline run.

        Priority:
          1. File location (structural): samples_with_files + series_file_count
          2. annotation_layer per-GSM distribution (only when sample files exist)

        Patterns:
          pattern1  - FASTQ-only (no files anywhere)
          pattern2  - Series-level files only
          pattern3_merged     - Sample files exist, some GSM has multiple layers
          pattern3_singleomic - Sample files exist, all GSMs covered, each single layer
          pattern4  - Sample files exist, different GSMs have distinct single layers, coverage < 100%
        """
        rows = self.conn.execute("""
            WITH sample_file_counts AS (
                SELECT
                    sam.series_accession,
                    sam.pipeline_run_id,
                    COUNT(DISTINCT sam.gsm_id)   AS actual_samples,
                    COUNT(DISTINCT ssf.gsm_id)   AS samples_with_files
                FROM sample sam
                LEFT JOIN sample_supplementary_file ssf
                    ON ssf.gsm_id = sam.gsm_id
                   AND ssf.series_accession = sam.series_accession
                   AND ssf.pipeline_run_id  = sam.pipeline_run_id
                WHERE sam.pipeline_run_id = ?
                GROUP BY sam.series_accession
            ),
            series_file_counts AS (
                SELECT series_accession, pipeline_run_id,
                       COUNT(id) AS series_file_count
                FROM series_supplementary_file
                WHERE pipeline_run_id = ?
                GROUP BY series_accession
            ),
            gsm_layer_counts AS (
                SELECT
                    san.series_accession,
                    san.gsm_id,
                    COUNT(al.id)                        AS layer_count,
                    GROUP_CONCAT(al.layer, ',')         AS layers
                FROM sample_annotation san
                JOIN annotation_layer al ON al.sample_annotation_id = san.id
                WHERE san.pipeline_run_id = ?
                GROUP BY san.series_accession, san.gsm_id
            ),
            layer_stats AS (
                SELECT
                    series_accession,
                    MAX(layer_count)                                     AS max_layers_per_gsm,
                    COUNT(DISTINCT CASE WHEN layer_count = 1
                          THEN layers END)                               AS distinct_single_layers,
                    SUM(CASE WHEN layer_count > 1 THEN 1 ELSE 0 END)    AS gsms_with_multiple_layers
                FROM gsm_layer_counts
                GROUP BY series_accession
            )
            SELECT
                s.accession,
                COALESCE(sfc.actual_samples, 0)       AS actual_samples,
                COALESCE(sfc.samples_with_files, 0)   AS samples_with_files,
                COALESCE(src.series_file_count, 0)    AS series_file_count,
                ls.max_layers_per_gsm,
                ls.distinct_single_layers,
                ls.gsms_with_multiple_layers
            FROM series s
            LEFT JOIN sample_file_counts sfc
                ON sfc.series_accession = s.accession
            LEFT JOIN series_file_counts src
                ON src.series_accession = s.accession
            LEFT JOIN layer_stats ls
                ON ls.series_accession = s.accession
            WHERE s.pipeline_run_id = ?
              AND s.hierarchy_role  = 'standalone'
        """, (run_id, run_id, run_id, run_id)).fetchall()

        results = []
        for row in rows:
            r = dict(row)
            accession          = r["accession"]
            actual_samples     = r["actual_samples"] or 0
            samples_with_files = r["samples_with_files"] or 0
            series_file_count  = r["series_file_count"] or 0
            max_layers         = r["max_layers_per_gsm"] or 0
            gsms_multi         = r["gsms_with_multiple_layers"] or 0
            all_covered        = (samples_with_files == actual_samples and actual_samples > 0)

            # Priority 1: file location
            if samples_with_files == 0 and series_file_count == 0:
                pattern = "pattern1"
                detail  = "FASTQ-only: no processed files at any level"
            elif samples_with_files == 0 and series_file_count > 0:
                pattern = "pattern2"
                detail  = f"Series-level only: {series_file_count} series file(s), 0 sample files"
            # Priority 2: annotation_layer distribution
            elif gsms_multi > 0:
                pattern = "pattern3_merged"
                detail  = (f"Merged multi-omic per GSM: {gsms_multi} GSM(s) carry multiple layers, "
                           f"{samples_with_files}/{actual_samples} samples covered")
            elif all_covered:
                pattern = "pattern3_singleomic"
                detail  = (f"Single-omic full coverage: {samples_with_files}/{actual_samples} "
                           f"samples covered, 1 layer per GSM")
            else:
                pattern = "pattern4"
                detail  = (f"Layer-split: {samples_with_files}/{actual_samples} samples have files, "
                           f"distinct single layers across GSMs")

            results.append({
                "accession":          accession,
                "pattern":            pattern,
                "detail":             detail,
                "actual_samples":     actual_samples,
                "samples_with_files": samples_with_files,
                "series_file_count":  series_file_count,
            })
        return results

    def save_upload_patterns(self, run_id: int,
                             classifications: list[dict]) -> None:
        """Persist upload_pattern and upload_pattern_detail to the series table."""
        for c in classifications:
            self.conn.execute(
                """UPDATE series
                   SET upload_pattern        = ?,
                       upload_pattern_detail = ?
                   WHERE accession = ? AND pipeline_run_id = ?""",
                (c["pattern"], c["detail"], c["accession"], run_id),
            )
        self.conn.commit()

    def get_upload_patterns(self, run_id: int) -> list[dict]:
        """Return upload_pattern classification for all standalone series."""
        rows = self.conn.execute(
            """SELECT accession, upload_pattern, upload_pattern_detail
               FROM series
               WHERE pipeline_run_id = ? AND hierarchy_role = 'standalone'
               ORDER BY accession""",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_annotations_for_series(
        self, series_accession: str, run_id: int,
        model_name: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Retrieve per-sample annotations, optionally filtered by model."""
        if model_name:
            rows = self.conn.execute(
                """SELECT sa.*, GROUP_CONCAT(al.layer, ',') AS layers
                   FROM sample_annotation sa
                   LEFT JOIN annotation_layer al
                     ON al.sample_annotation_id = sa.id
                   WHERE sa.series_accession = ?
                     AND sa.pipeline_run_id = ?
                     AND sa.model_name = ?
                   GROUP BY sa.id""",
                (series_accession, run_id, model_name),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """SELECT sa.*, GROUP_CONCAT(al.layer, ',') AS layers
                   FROM sample_annotation sa
                   LEFT JOIN annotation_layer al
                     ON al.sample_annotation_id = sa.id
                   WHERE sa.series_accession = ?
                     AND sa.pipeline_run_id = ?
                   GROUP BY sa.id""",
                (series_accession, run_id),
            ).fetchall()
        results = []
        for row in rows:
            d = dict(row)
            d["measured_layers"] = d.pop("layers", "").split(",") if d.get("layers") else []
            results.append(d)
        return results
