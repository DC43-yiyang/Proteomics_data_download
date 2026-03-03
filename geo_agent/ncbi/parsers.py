import logging
import re
from typing import Any

from geo_agent.models.dataset import GEODataset, SupplementaryFile
from geo_agent.models.sample import GEOSample

logger = logging.getLogger(__name__)


def parse_esearch_response(data: dict) -> tuple[list[str], int]:
    """Parse esearch JSON response to extract UIDs and total count.

    Args:
        data: Raw JSON response from esearch

    Returns:
        (list of UID strings, total count of matching records)
    """
    result = data.get("esearchresult", {})
    uids = result.get("idlist", [])
    count = int(result.get("count", 0))
    return uids, count


def parse_esummary_to_datasets(data: dict) -> list[GEODataset]:
    """Parse esummary JSON response into GEODataset objects.

    Handles the GDS database summary format. Each entry contains fields like
    Accession, title, summary, taxon, gdsType, n_samples, FTPLink, etc.

    Args:
        data: Raw JSON response from esummary

    Returns:
        List of GEODataset objects populated with metadata
    """
    datasets = []
    result = data.get("result", {})

    for uid, entry in result.items():
        if not isinstance(entry, dict):
            continue

        # Extract accession - try multiple field names
        accession = entry.get("accession", entry.get("Accession", ""))
        if not accession:
            # For GDS database, the GSE accession may be in the GSE field
            gse = entry.get("gse", "")
            accession = f"GSE{gse}" if gse else f"UID:{uid}"

        # Extract organism
        organism = ""
        taxon = entry.get("taxon", "")
        if taxon:
            organism = taxon
        elif "organism_ch1" in entry:
            organism = entry["organism_ch1"]

        # Extract FTP link
        ftp_link = entry.get("ftplink", entry.get("FTPLink", ""))

        # Extract supplementary files if present
        supp_files = []
        suppfile = entry.get("suppfile", "")
        if suppfile:
            for fname in suppfile.split(";"):
                fname = fname.strip()
                if fname:
                    url = f"{ftp_link}suppl/{fname}" if ftp_link else ""
                    supp_files.append(SupplementaryFile(name=fname, url=url))

        dataset = GEODataset(
            accession=accession,
            uid=uid,
            title=entry.get("title", ""),
            summary=entry.get("summary", ""),
            organism=organism,
            platform=entry.get("gpl", entry.get("GPL", "")),
            series_type=entry.get("gdstype", entry.get("entrytype", "")),
            sample_count=_safe_int(entry.get("n_samples", entry.get("samplecount", 0))),
            ftp_link=ftp_link,
            supplementary_files=supp_files,
        )
        datasets.append(dataset)

    return datasets


def _safe_int(value: Any) -> int:
    """Safely convert a value to int, returning 0 on failure."""
    try:
        return int(value)
    except (ValueError, TypeError):
        return 0


def parse_soft_text(soft_text: str) -> dict[str, str]:
    """Parse GEO SOFT format text to extract key fields.

    SOFT format uses lines like:
        !Series_overall_design = Intestinal epithelial lymphocytes...
        !Series_summary = We focus on characterizing...
        !Series_contributor = Smith,,John

    Args:
        soft_text: Raw SOFT format text from GEO acc.cgi

    Returns:
        Dict with extracted fields: overall_design, summary, contributors, etc.
    """
    fields: dict[str, str] = {}

    # Fields we want to extract (single-value)
    single_fields = {
        "!Series_overall_design": "overall_design",
        "!Series_summary": "summary",
        "!Series_title": "title",
        "!Series_status": "status",
        "!Series_submission_date": "submission_date",
        "!Series_last_update_date": "last_update_date",
        "!Series_geo_accession": "accession",
    }

    # Fields that can have multiple values (collect as list then join)
    multi_fields = {
        "!Series_type": "series_types",
        "!Series_contributor": "contributors",
        "!Series_sample_id": "sample_ids",
        "!Series_supplementary_file": "supplementary_files",
    }

    multi_values: dict[str, list[str]] = {v: [] for v in multi_fields.values()}

    for line in soft_text.splitlines():
        line = line.strip()
        if not line or not line.startswith("!"):
            continue

        # Split on first " = "
        if " = " not in line:
            continue
        key, _, value = line.partition(" = ")
        key = key.strip()
        value = value.strip()

        if key in single_fields:
            fields[single_fields[key]] = value
        elif key in multi_fields:
            multi_values[multi_fields[key]].append(value)

    # Join multi-value fields
    for field_name, values in multi_values.items():
        if values:
            fields[field_name] = "; ".join(values)

    return fields


def parse_family_soft(soft_text: str) -> list[GEOSample]:
    """Parse Family SOFT format (targ=gsm) into per-sample GEOSample objects.

    Family SOFT contains multiple ^SAMPLE blocks, each with sample-level
    metadata like title, characteristics, molecule, library_source, etc.

    Args:
        soft_text: Raw Family SOFT text from GEO acc.cgi (targ=gsm)

    Returns:
        List of GEOSample objects, one per sample block
    """
    samples: list[GEOSample] = []

    # Split on ^SAMPLE boundaries
    blocks = re.split(r"^\^SAMPLE\s*=\s*", soft_text, flags=re.MULTILINE)

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        # First line is the accession (rest of the ^SAMPLE = line)
        lines = block.splitlines()
        accession = lines[0].strip()
        if not accession.startswith("GSM"):
            continue

        title = ""
        organism = ""
        molecule = ""
        library_source = ""
        description = ""
        characteristics: dict[str, str] = {}
        supplementary_files: list[str] = []

        for line in lines[1:]:
            line = line.strip()
            if not line or not line.startswith("!"):
                continue
            if " = " not in line:
                continue

            key, _, value = line.partition(" = ")
            key = key.strip()
            value = value.strip()

            if key == "!Sample_title":
                title = value
            elif key == "!Sample_organism_ch1":
                organism = value
            elif key == "!Sample_molecule_ch1":
                molecule = value
            elif key == "!Sample_library_source":
                library_source = value
            elif key == "!Sample_description":
                if description:
                    description += "; " + value
                else:
                    description = value
            elif key == "!Sample_characteristics_ch1":
                # Format: "key: value" or just "value"
                if ": " in value:
                    char_key, _, char_val = value.partition(": ")
                    characteristics[char_key.strip()] = char_val.strip()
                else:
                    characteristics[value] = value
            elif key == "!Sample_supplementary_file" or key.startswith("!Sample_supplementary_file_"):
                if value and value.lower() != "none":
                    supplementary_files.append(value)

        samples.append(GEOSample(
            accession=accession,
            title=title,
            organism=organism,
            molecule=molecule,
            characteristics=characteristics,
            library_source=library_source,
            supplementary_files=supplementary_files,
            description=description,
        ))

    return samples
