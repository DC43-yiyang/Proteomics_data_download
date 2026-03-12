"""Rule-based heuristic for detecting layer-split patterns in GEO samples.

When GEO authors split one biological sample into multiple GSMs by omic layer
(e.g., GEX + ADT + HTO -> 3 GSMs for 1 bio sample), the naive count(GSM)
inflates the true biological sample count.

This module detects such patterns from sample titles and metadata,
producing a hint dict that can be passed to the LLM for confirmation.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

logger = logging.getLogger(__name__)

# Layer-indicating keywords (lowercase).  These are short tokens that
# commonly appear in GEO sample titles to distinguish omic layers
# within a layer-split upload.
_LAYER_KEYWORDS_LOWER: frozenset[str] = frozenset({
    # RNA / gene expression
    "gex", "rna", "scrna", "mrna", "gene expression",
    # Protein / surface
    "adt", "surface", "abseq", "protein",
    # Chromatin
    "atac", "scatac",
    # VDJ / immune repertoire
    "vdj", "tcr", "bcr", "gd tcr", "ab tcr",
    # Cell labels / hashing
    "hto", "hashtag", "fb",
    # CRISPR
    "crispr", "sgrna",
})

# Separators tried in order of preference (most structured first).
_SEPARATORS = [", ", ",", "_"]


def _find_layer_token(tokens: list[str]) -> tuple[str | None, int]:
    """Find a layer keyword among tokens (case-insensitive).

    Returns (matched_keyword_original_case, token_index) or (None, -1).
    """
    for i, token in enumerate(tokens):
        if token.strip().lower() in _LAYER_KEYWORDS_LOWER:
            return token.strip(), i
    return None, -1


def _bio_label(tokens: list[str], layer_idx: int, sep: str) -> str:
    """Reconstruct the biological sample label by removing the layer token."""
    remaining = [t for j, t in enumerate(tokens) if j != layer_idx]
    joiner = sep if sep else " "
    return joiner.join(remaining).strip()


def detect_layer_split(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Analyze sample titles/metadata to detect suspected layer-split.

    Args:
        samples: list of sample dicts with at least ``sample_title`` and
                 optionally ``gsm_id`` and ``library_source``.

    Returns:
        {
            "suspected_layer_split": bool,
            "confidence": "high" | "medium" | "low",
            "layer_keywords_found": ["GEX", "ADT", ...],
            "distinct_library_sources": ["transcriptomic", "other", ...],
            "heuristic_groups": [
                {"bio_sample_label": "K5 PDX", "gsm_ids": [...], "layers": [...]},
                ...
            ],
            "heuristic_bio_sample_count": int,
            "heuristic_split_ratio": "1:3",
        }
    """
    if not samples or len(samples) < 2:
        return _negative_result(samples, [])

    titles = [s.get("sample_title", "") for s in samples]
    gsm_ids = [s.get("gsm_id", "") for s in samples]

    # Collect distinct library_source values
    library_sources: set[str] = set()
    for s in samples:
        src = (s.get("library_source") or "").strip().lower()
        if src:
            library_sources.add(src)

    # Try each separator strategy; pick the one that matches the most samples
    best_matches: list[tuple[str, str, str]] = []  # (gsm_id, keyword, bio_label)

    for sep in _SEPARATORS:
        matches: list[tuple[str, str, str]] = []
        for gsm_id, title in zip(gsm_ids, titles):
            if sep in title:
                tokens = [t.strip() for t in title.split(sep)]
            else:
                tokens = [title.strip()]
            kw, idx = _find_layer_token(tokens)
            if kw is not None:
                label = _bio_label(tokens, idx, sep)
                matches.append((gsm_id, kw, label))
        if len(matches) > len(best_matches):
            best_matches = matches

    # Also try whole-title match (title IS the keyword)
    whole_matches: list[tuple[str, str, str]] = []
    for gsm_id, title in zip(gsm_ids, titles):
        if title.strip().lower() in _LAYER_KEYWORDS_LOWER:
            whole_matches.append((gsm_id, title.strip(), ""))
    if len(whole_matches) > len(best_matches):
        best_matches = whole_matches

    # Need >=2 matched samples with >=2 different keywords
    keywords_found = sorted(set(kw for _, kw, _ in best_matches))
    if len(best_matches) < 2 or len(keywords_found) < 2:
        return _negative_result(samples, sorted(library_sources))

    # At least half the samples should match for confidence
    match_fraction = len(best_matches) / len(samples)
    if match_fraction < 0.5:
        return _negative_result(samples, sorted(library_sources))

    # Group matched samples by bio_label
    groups: dict[str, list[tuple[str, str]]] = {}
    for gsm_id, kw, label in best_matches:
        groups.setdefault(label, []).append((gsm_id, kw))

    heuristic_groups = []
    for label, members in sorted(groups.items()):
        heuristic_groups.append({
            "bio_sample_label": label,
            "gsm_ids": [gid for gid, _ in members],
            "layers": sorted(set(kw for _, kw in members)),
        })

    # Compute split ratio
    group_sizes = [len(g["gsm_ids"]) for g in heuristic_groups]
    size_counts = Counter(group_sizes)
    most_common_size = size_counts.most_common(1)[0][0] if size_counts else 0
    consistent_groups = len(size_counts) == 1
    ratio = f"1:{most_common_size}" if most_common_size > 1 else ""

    # Confidence assessment
    has_diverse_sources = len(library_sources) > 1
    if consistent_groups and has_diverse_sources and match_fraction >= 0.8:
        confidence = "high"
    elif consistent_groups or has_diverse_sources:
        confidence = "medium"
    else:
        confidence = "low"

    num_unmatched = len(samples) - len(best_matches)

    logger.info(
        "Layer-split detected: %d groups, ratio=%s, keywords=%s, "
        "confidence=%s, matched=%d/%d",
        len(heuristic_groups), ratio, keywords_found,
        confidence, len(best_matches), len(samples),
    )

    return {
        "suspected_layer_split": True,
        "confidence": confidence,
        "layer_keywords_found": keywords_found,
        "distinct_library_sources": sorted(library_sources),
        "heuristic_groups": heuristic_groups,
        "heuristic_bio_sample_count": len(heuristic_groups) + num_unmatched,
        "heuristic_split_ratio": ratio,
    }


def _negative_result(
    samples: list[dict[str, Any]],
    library_sources: list[str],
) -> dict[str, Any]:
    """Return a 'no split detected' result."""
    return {
        "suspected_layer_split": False,
        "confidence": "low",
        "layer_keywords_found": [],
        "distinct_library_sources": library_sources,
        "heuristic_groups": [],
        "heuristic_bio_sample_count": len(samples),
        "heuristic_split_ratio": "",
    }
