#!/usr/bin/env python3
"""Database roundtrip test.

Creates a temporary SQLite DB, inserts fixture data into all tables via
DatabaseRepository methods, reads it back, and verifies correctness.
No NCBI or LLM calls needed.
"""

import sys
import tempfile
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from geo_agent.db import Database, DatabaseRepository
from geo_agent.models.dataset import GEODataset, SupplementaryFile
from geo_agent.models.query import SearchQuery


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        print(f"[db] Using temporary database: {db_path}")

        with Database(db_path) as db:
            repo = DatabaseRepository(db)

            # ── Step 0: Create pipeline run ──────────────────────
            query = SearchQuery(
                data_type="CITE-seq",
                organism="Homo sapiens",
                disease="breast cancer",
                tissue="PBMC",
                max_results=10,
            )
            run_id = repo.create_run(query)
            assert run_id is not None and run_id > 0, f"Expected positive run_id, got {run_id}"
            print(f"[ok] pipeline_run created: id={run_id}")

            # ── Step 1: Save series (GEOSearchSkill) ─────────────
            ds1 = GEODataset(
                accession="GSE207438",
                uid="200207438",
                title="Immune Profiling-Based Treatment",
                summary="We performed CITE-seq on PBMCs...",
                organism="Homo sapiens",
                platform="GPL24676",
                series_type="Expression profiling by high throughput sequencing",
                sample_count=48,
                overall_design="CITE-seq was performed...",
                ftp_link="ftp://ftp.ncbi.nlm.nih.gov/geo/series/GSE207nnn/GSE207438/",
                supplementary_files=[
                    SupplementaryFile(name="GSE207438_RAW.tar", url="ftp://example.com/RAW.tar", size_bytes=1024000),
                    SupplementaryFile(name="GSE207438_counts.h5ad", url="ftp://example.com/counts.h5ad"),
                ],
                relations=["SuperSeries of: GSE207437", "BioProject: https://www.ncbi.nlm.nih.gov/bioproject/PRJNA123"],
            )
            ds2 = GEODataset(
                accession="GSE266455",
                uid="200266455",
                title="Multi-omics PBMC Analysis",
                summary="Another CITE-seq dataset...",
                organism="Homo sapiens",
                platform="GPL24676",
                sample_count=24,
            )
            repo.save_series_batch([ds1, ds2], run_id)

            # Verify series
            series_list = repo.get_series_for_run(run_id)
            assert len(series_list) == 2, f"Expected 2 series, got {len(series_list)}"
            accs = {s["accession"] for s in series_list}
            assert accs == {"GSE207438", "GSE266455"}, f"Unexpected accessions: {accs}"
            print(f"[ok] 2 series saved and retrieved")

            # Verify relations
            rels = repo.get_series_relations("GSE207438", run_id)
            assert len(rels) == 2, f"Expected 2 relations, got {len(rels)}"
            assert "SuperSeries of: GSE207437" in rels
            print(f"[ok] series_relation: {len(rels)} relations retrieved")

            # Save and verify SOFT text
            soft_text = "^SERIES = GSE207438\n!Series_title = Test Series\n"
            repo.save_series_soft_text("GSE207438", run_id, soft_text)
            retrieved_soft = repo.get_series_soft_text("GSE207438", run_id)
            assert retrieved_soft == soft_text, "SOFT text roundtrip failed"
            none_soft = repo.get_series_soft_text("GSE266455", run_id)
            assert none_soft is None, "Expected None for missing SOFT text"
            print(f"[ok] series_soft_text roundtrip verified")

            # ── Step 2: Update hierarchy ─────────────────────────
            repo.update_hierarchy("GSE207438", run_id, "standalone", None, True)
            repo.update_hierarchy("GSE266455", run_id, "sub", "GSE999999", True)
            repo.upsert_external_series("GSE999999", run_id, "Parent SuperSeries", "super", None)

            series_list = repo.get_series_for_run(run_id)
            roles = {s["accession"]: s["hierarchy_role"] for s in series_list}
            assert roles["GSE207438"] == "standalone"
            assert roles["GSE266455"] == "sub"
            assert roles["GSE999999"] == "super"
            print(f"[ok] hierarchy updated: {roles}")

            # ── Step 4: Save parsed samples ──────────────────────
            sample_data = [
                {
                    "gsm_id": "GSM8247203",
                    "sample_geo_accession": "GSM8247203",
                    "sample_title": "Patient1, CITE-seq GEX",
                    "sample_status": "Public on Oct 01 2025",
                    "organism": "Homo sapiens",
                    "source_name": "PBMC",
                    "library_strategy": "RNA-Seq",
                    "library_source": "transcriptomic single cell",
                    "molecule": "polyA RNA",
                    "platform_id": "GPL24676",
                    "description": "GEX library from CITE-seq",
                    "library_type": "GEX",
                    "characteristics": {
                        "cell type": "PBMC",
                        "tissue": "blood",
                        "disease": "healthy",
                    },
                    "characteristics_rows": [
                        "cell type: PBMC",
                        "tissue: blood",
                        "disease: healthy",
                    ],
                    "supplementary_files": [
                        "ftp://example.com/GSM8247203_barcodes.tsv.gz",
                        "ftp://example.com/GSM8247203_features.tsv.gz",
                    ],
                    "supplementary_file_names": [
                        "GSM8247203_barcodes.tsv.gz",
                        "GSM8247203_features.tsv.gz",
                    ],
                    "relation_sra": ["https://www.ncbi.nlm.nih.gov/sra?term=SRX12345"],
                    "relation_biosample": ["https://www.ncbi.nlm.nih.gov/biosample/SAMN12345"],
                    "relation_other": [],
                    "notes": ["no_supplementary_files"],
                },
                {
                    "gsm_id": "GSM8247204",
                    "sample_title": "Patient1, CITE-seq ADT",
                    "organism": "Homo sapiens",
                    "library_type": "ADT",
                    "characteristics": {"cell type": "PBMC", "molecule subtype": "surface protein"},
                    "characteristics_rows": ["cell type: PBMC", "molecule subtype: surface protein"],
                    "supplementary_files": [],
                    "supplementary_file_names": [],
                    "relation_sra": [],
                    "relation_biosample": [],
                    "relation_other": [],
                    "notes": [],
                },
            ]
            repo.save_samples_batch("GSE207438", run_id, sample_data)

            # Verify samples
            samples = repo.get_samples_for_series("GSE207438", run_id)
            assert len(samples) == 2, f"Expected 2 samples, got {len(samples)}"

            gsm203 = next(s for s in samples if s["gsm_id"] == "GSM8247203")
            assert gsm203["library_type"] == "GEX"
            assert gsm203["characteristics"]["cell type"] == "PBMC"
            assert gsm203["characteristics"]["tissue"] == "blood"
            print(f"[ok] 2 samples saved with characteristics (EAV roundtrip verified)")

            # Verify supplementary files via raw SQL (repo doesn't expose a getter)
            sup_count = db.conn.execute(
                "SELECT COUNT(*) FROM sample_supplementary_file WHERE pipeline_run_id = ?",
                (run_id,),
            ).fetchone()[0]
            assert sup_count == 2, f"Expected 2 sample supplementary files, got {sup_count}"
            print(f"[ok] sample_supplementary_file: {sup_count} rows")

            # Verify relations
            rel_count = db.conn.execute(
                "SELECT COUNT(*) FROM sample_relation WHERE pipeline_run_id = ?",
                (run_id,),
            ).fetchone()[0]
            assert rel_count == 2, f"Expected 2 sample relations, got {rel_count}"
            print(f"[ok] sample_relation: {rel_count} rows")

            # Verify notes
            note_count = db.conn.execute(
                "SELECT COUNT(*) FROM sample_note WHERE pipeline_run_id = ?",
                (run_id,),
            ).fetchone()[0]
            assert note_count == 1, f"Expected 1 sample note, got {note_count}"
            print(f"[ok] sample_note: {note_count} rows")

            # ── Step 5: Save LLM annotations ────────────────────
            series_ann = {
                "disease_normalized": "healthy",
                "tissue_normalized": "PBMC",
                "sample_count": 2,
                "reasoning": "Both samples are from CITE-seq on healthy donor PBMCs.",
            }
            repo.save_series_annotation("GSE207438", run_id, "qwen3:30b-a3b", series_ann)

            sample_anns = [
                {
                    "gsm_id": "GSM8247203",
                    "sample_title": "Patient1, CITE-seq GEX",
                    "measured_layers": ["RNA"],
                    "platform": "10x Chromium 3'",
                    "experiment": "CITE-seq",
                    "assay": "scRNA-seq",
                    "disease": "healthy",
                    "tissue": "PBMC",
                    "tissue_subtype": "",
                    "confidence": 0.95,
                    "evidence": "GEX library, RNA-Seq strategy",
                    "in_input": True,
                },
                {
                    "gsm_id": "GSM8247204",
                    "sample_title": "Patient1, CITE-seq ADT",
                    "measured_layers": ["protein_surface"],
                    "platform": "10x Chromium 3'",
                    "experiment": "CITE-seq",
                    "assay": "CITE-seq ADT",
                    "disease": "healthy",
                    "tissue": "PBMC",
                    "tissue_subtype": "",
                    "confidence": 0.90,
                    "evidence": "ADT library, surface protein",
                    "in_input": True,
                },
            ]
            repo.save_sample_annotations_batch("GSE207438", run_id, "qwen3:30b-a3b", sample_anns)

            # Verify annotations
            anns = repo.get_annotations_for_series("GSE207438", run_id, "qwen3:30b-a3b")
            assert len(anns) == 2, f"Expected 2 annotations, got {len(anns)}"
            gsm203_ann = next(a for a in anns if a["gsm_id"] == "GSM8247203")
            assert gsm203_ann["measured_layers"] == ["RNA"], f"Got layers: {gsm203_ann['measured_layers']}"
            assert gsm203_ann["confidence"] == 0.95
            gsm204_ann = next(a for a in anns if a["gsm_id"] == "GSM8247204")
            assert gsm204_ann["measured_layers"] == ["protein_surface"]
            print(f"[ok] 2 sample annotations saved with measured_layers junction table")

            # Verify series annotation
            sa_row = db.conn.execute(
                "SELECT * FROM series_annotation WHERE series_accession = ? AND pipeline_run_id = ?",
                ("GSE207438", run_id),
            ).fetchone()
            assert sa_row is not None
            assert dict(sa_row)["disease_normalized"] == "healthy"
            assert dict(sa_row)["reasoning"].startswith("Both samples")
            print(f"[ok] series_annotation verified")

            # ── Finish run ───────────────────────────────────────
            repo.finish_run(run_id, total_found=35, status="completed")
            run_row = db.conn.execute(
                "SELECT * FROM pipeline_run WHERE id = ?", (run_id,)
            ).fetchone()
            assert dict(run_row)["status"] == "completed"
            assert dict(run_row)["total_found"] == 35
            assert dict(run_row)["finished_at"] is not None
            print(f"[ok] pipeline_run finished: status=completed, total_found=35")

            # ── Table summary ────────────────────────────────────
            print("\n--- Table Row Counts ---")
            tables = [
                "pipeline_run", "series", "series_supplementary_file",
                "series_relation", "series_soft_text", "sample",
                "sample_characteristic", "sample_supplementary_file",
                "sample_relation", "sample_note", "series_annotation",
                "sample_annotation", "annotation_layer", "schema_version",
            ]
            for table in tables:
                count = db.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                print(f"  {table}: {count}")

        print(f"\n{'='*50}")
        print("ALL ROUNDTRIP TESTS PASSED")
        print(f"{'='*50}")


if __name__ == "__main__":
    main()
