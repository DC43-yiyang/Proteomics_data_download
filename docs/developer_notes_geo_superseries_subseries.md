# Developer note: GEO dataset nesting (SuperSeries vs SubSeries)

## Context

When querying single-cell data via NCBI E-utilities, GEO’s nesting for multi-omics clinical cohorts appears as follows:

- **SubSeries**: Holds a single omics type. For example, GSE317605 contains only CITE-seq data (168 samples).
- **SuperSeries**: A logical parent that bundles multiple sub-series from the same cohort. For example, GSE317606 is a SuperSeries that groups the CITE-seq data above with Spatial Transcriptomics (GSE316402, 12 samples) from the same patients, for a total of 180 samples.

## Current decision: keep isolated, no special handling

- **Rationale**: The tool’s main goal is to fetch homogeneous, single data types (e.g. CITE-seq only) for analysis.
- **Natural filtering**: SearchQuery forces specific technology terms (e.g. CITE-seq), so NCBI search returns the concrete SubSeries and tends to exclude the SuperSeries wrapper.
- **Conclusion**: For the MVP, we do not add SuperSeries/SubSeries logic in parsers or data models.

## Future work

If multi-omics workflows are needed later (e.g. CITE-seq plus spatial transcriptomics or scATAC-seq), this can be enabled with:

1. **Parser**: In `ncbi/parsers.py`, when parsing esummary, extract Relation fields that point to SuperSeries.
2. **Report**: In ReportSkill, flag datasets that have linked multi-omics (e.g. “💡 Linked multi-omics (SuperSeries: GSEXXXXX)”).
3. **Agent**: Add a related-search Skill so users can, from a SuperSeries, one-click fetch all omics for the same cohort.
