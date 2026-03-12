"""Schema migrations for the GEO Agent database.

Each migration is a (version, description, sql) tuple. Migrations are applied
in order and are idempotent -- the schema_version table tracks what has been
applied.
"""

import logging
import sqlite3

logger = logging.getLogger(__name__)

_V1_SQL = """
-- Pipeline run provenance
CREATE TABLE IF NOT EXISTS pipeline_run (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    finished_at     TEXT,
    data_type       TEXT NOT NULL,
    organism        TEXT,
    disease         TEXT,
    tissue          TEXT,
    max_results     INTEGER NOT NULL DEFAULT 100,
    total_found     INTEGER,
    status          TEXT NOT NULL DEFAULT 'running'
);

-- Step 01: GEO Search results
CREATE TABLE IF NOT EXISTS series (
    accession         TEXT    NOT NULL,
    pipeline_run_id   INTEGER NOT NULL,
    uid               TEXT    NOT NULL DEFAULT '',
    title             TEXT    NOT NULL DEFAULT '',
    summary           TEXT    NOT NULL DEFAULT '',
    organism          TEXT    NOT NULL DEFAULT '',
    platform          TEXT    NOT NULL DEFAULT '',
    series_type       TEXT    NOT NULL DEFAULT '',
    sample_count      INTEGER NOT NULL DEFAULT 0,
    overall_design    TEXT    NOT NULL DEFAULT '',
    ftp_link          TEXT    NOT NULL DEFAULT '',
    relevance_score   REAL    NOT NULL DEFAULT 0.0,
    is_valid          INTEGER NOT NULL DEFAULT 0,
    validation_notes  TEXT    NOT NULL DEFAULT '',

    -- Step 02: Hierarchy fields
    hierarchy_role    TEXT,
    in_search_results INTEGER NOT NULL DEFAULT 1,
    parent_accession  TEXT,

    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    PRIMARY KEY (accession, pipeline_run_id),
    FOREIGN KEY (pipeline_run_id) REFERENCES pipeline_run(id)
);

CREATE INDEX IF NOT EXISTS idx_series_run ON series(pipeline_run_id);
CREATE INDEX IF NOT EXISTS idx_series_role ON series(hierarchy_role);

CREATE TABLE IF NOT EXISTS series_supplementary_file (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    series_accession TEXT    NOT NULL,
    pipeline_run_id  INTEGER NOT NULL,
    name             TEXT    NOT NULL DEFAULT '',
    url              TEXT    NOT NULL DEFAULT '',
    size_bytes       INTEGER,

    FOREIGN KEY (series_accession, pipeline_run_id)
        REFERENCES series(accession, pipeline_run_id)
);

CREATE TABLE IF NOT EXISTS series_relation (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    series_accession TEXT    NOT NULL,
    pipeline_run_id  INTEGER NOT NULL,
    relation_text    TEXT    NOT NULL,

    FOREIGN KEY (series_accession, pipeline_run_id)
        REFERENCES series(accession, pipeline_run_id)
);

-- Raw Series SOFT text storage
CREATE TABLE IF NOT EXISTS series_soft_text (
    series_accession TEXT    NOT NULL,
    pipeline_run_id  INTEGER NOT NULL,
    soft_text        TEXT    NOT NULL,
    fetched_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    PRIMARY KEY (series_accession, pipeline_run_id),
    FOREIGN KEY (series_accession, pipeline_run_id)
        REFERENCES series(accession, pipeline_run_id)
);

-- Step 04: Parsed Family SOFT samples
CREATE TABLE IF NOT EXISTS sample (
    gsm_id              TEXT    NOT NULL,
    series_accession    TEXT    NOT NULL,
    pipeline_run_id     INTEGER NOT NULL,
    sample_geo_accession TEXT   NOT NULL DEFAULT '',
    sample_title        TEXT    NOT NULL DEFAULT '',
    sample_status       TEXT    NOT NULL DEFAULT '',
    organism            TEXT    NOT NULL DEFAULT '',
    source_name         TEXT    NOT NULL DEFAULT '',
    library_strategy    TEXT    NOT NULL DEFAULT '',
    library_source      TEXT    NOT NULL DEFAULT '',
    molecule            TEXT    NOT NULL DEFAULT '',
    platform_id         TEXT    NOT NULL DEFAULT '',
    description         TEXT    NOT NULL DEFAULT '',
    library_type        TEXT    NOT NULL DEFAULT '',

    created_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    PRIMARY KEY (gsm_id, series_accession, pipeline_run_id),
    FOREIGN KEY (series_accession, pipeline_run_id)
        REFERENCES series(accession, pipeline_run_id)
);

CREATE INDEX IF NOT EXISTS idx_sample_series ON sample(series_accession, pipeline_run_id);

-- Dynamic key-value characteristics (EAV pattern)
CREATE TABLE IF NOT EXISTS sample_characteristic (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    gsm_id           TEXT    NOT NULL,
    series_accession TEXT    NOT NULL,
    pipeline_run_id  INTEGER NOT NULL,
    char_key         TEXT    NOT NULL,
    char_value       TEXT    NOT NULL,
    raw_row          TEXT    NOT NULL DEFAULT '',

    FOREIGN KEY (gsm_id, series_accession, pipeline_run_id)
        REFERENCES sample(gsm_id, series_accession, pipeline_run_id)
);

CREATE INDEX IF NOT EXISTS idx_sample_char_key ON sample_characteristic(char_key);
CREATE INDEX IF NOT EXISTS idx_sample_char_gsm ON sample_characteristic(gsm_id, series_accession, pipeline_run_id);

CREATE TABLE IF NOT EXISTS sample_supplementary_file (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    gsm_id           TEXT    NOT NULL,
    series_accession TEXT    NOT NULL,
    pipeline_run_id  INTEGER NOT NULL,
    url              TEXT    NOT NULL,
    file_name        TEXT    NOT NULL DEFAULT '',

    FOREIGN KEY (gsm_id, series_accession, pipeline_run_id)
        REFERENCES sample(gsm_id, series_accession, pipeline_run_id)
);

CREATE TABLE IF NOT EXISTS sample_relation (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    gsm_id           TEXT    NOT NULL,
    series_accession TEXT    NOT NULL,
    pipeline_run_id  INTEGER NOT NULL,
    relation_type    TEXT    NOT NULL,
    relation_url     TEXT    NOT NULL,

    FOREIGN KEY (gsm_id, series_accession, pipeline_run_id)
        REFERENCES sample(gsm_id, series_accession, pipeline_run_id)
);

CREATE TABLE IF NOT EXISTS sample_note (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    gsm_id           TEXT    NOT NULL,
    series_accession TEXT    NOT NULL,
    pipeline_run_id  INTEGER NOT NULL,
    note             TEXT    NOT NULL,

    FOREIGN KEY (gsm_id, series_accession, pipeline_run_id)
        REFERENCES sample(gsm_id, series_accession, pipeline_run_id)
);

-- Step 05: LLM Annotations
CREATE TABLE IF NOT EXISTS series_annotation (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    series_accession    TEXT    NOT NULL,
    pipeline_run_id     INTEGER NOT NULL,
    model_name          TEXT    NOT NULL,
    disease_normalized  TEXT    NOT NULL DEFAULT '',
    tissue_normalized   TEXT    NOT NULL DEFAULT '',
    sample_count        INTEGER NOT NULL DEFAULT 0,
    reasoning           TEXT    NOT NULL DEFAULT '',
    annotated_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    UNIQUE (series_accession, pipeline_run_id, model_name),
    FOREIGN KEY (series_accession, pipeline_run_id)
        REFERENCES series(accession, pipeline_run_id)
);

CREATE TABLE IF NOT EXISTS sample_annotation (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    gsm_id              TEXT    NOT NULL,
    series_accession    TEXT    NOT NULL,
    pipeline_run_id     INTEGER NOT NULL,
    model_name          TEXT    NOT NULL,
    sample_title        TEXT    NOT NULL DEFAULT '',
    platform            TEXT    NOT NULL DEFAULT '',
    experiment          TEXT    NOT NULL DEFAULT '',
    assay               TEXT    NOT NULL DEFAULT '',
    disease             TEXT    NOT NULL DEFAULT '',
    tissue              TEXT    NOT NULL DEFAULT '',
    tissue_subtype      TEXT    NOT NULL DEFAULT '',
    confidence          REAL    NOT NULL DEFAULT 0.0,
    evidence            TEXT    NOT NULL DEFAULT '',
    in_input            INTEGER,
    annotated_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    UNIQUE (gsm_id, series_accession, pipeline_run_id, model_name),
    FOREIGN KEY (gsm_id, series_accession, pipeline_run_id)
        REFERENCES sample(gsm_id, series_accession, pipeline_run_id)
);

CREATE INDEX IF NOT EXISTS idx_sample_ann_series ON sample_annotation(series_accession, pipeline_run_id, model_name);

-- measured_layers junction table
CREATE TABLE IF NOT EXISTS annotation_layer (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    sample_annotation_id    INTEGER NOT NULL,
    layer                   TEXT    NOT NULL,

    FOREIGN KEY (sample_annotation_id)
        REFERENCES sample_annotation(id)
);

CREATE INDEX IF NOT EXISTS idx_ann_layer_parent ON annotation_layer(sample_annotation_id);
"""

_V2_SQL = """
ALTER TABLE series_annotation ADD COLUMN is_layer_split INTEGER;
ALTER TABLE series_annotation ADD COLUMN biological_sample_count INTEGER;
ALTER TABLE series_annotation ADD COLUMN layer_split_ratio TEXT NOT NULL DEFAULT '';
"""

_V3_SQL = """
ALTER TABLE series ADD COLUMN upload_pattern TEXT;
ALTER TABLE series ADD COLUMN upload_pattern_detail TEXT NOT NULL DEFAULT '';
"""

# Append-only migration list. NEVER modify existing entries.
_MIGRATIONS: list[tuple[int, str, str]] = [
    (1, "Initial schema: series, samples, annotations", _V1_SQL),
    (2, "Add layer-split detection columns to series_annotation", _V2_SQL),
    (3, "Add upload_pattern classification columns to series", _V3_SQL),
]


def apply_migrations(conn: sqlite3.Connection) -> None:
    """Apply any pending migrations to the database."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version     INTEGER PRIMARY KEY,
            applied_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            description TEXT NOT NULL DEFAULT ''
        )
    """)
    current = _current_version(conn)

    for version, desc, sql in _MIGRATIONS:
        if version <= current:
            continue
        logger.info("Applying migration v%d: %s", version, desc)
        conn.executescript(sql)
        conn.execute(
            "INSERT INTO schema_version (version, description) VALUES (?, ?)",
            (version, desc),
        )
        conn.commit()


def _current_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
        return row[0] or 0
    except sqlite3.OperationalError:
        return 0
