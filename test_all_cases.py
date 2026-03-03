"""Test SampleSelectorSkill on all 20 local Family SOFT files."""
import os
import json
import anthropic
from collections import Counter
from geo_agent.config import load_config
from geo_agent.ncbi.parsers import parse_family_soft
from geo_agent.skills.sample_selector import SampleSelectorSkill

config = load_config()
llm_client = anthropic.Anthropic(
    api_key=config.anthropic_api_key,
    base_url=config.anthropic_base_url,
)

skill = SampleSelectorSkill(
    ncbi_client=None,
    llm_client=llm_client,
    model=config.llm_model,
    confidence_threshold=0.7,
)

SOFT_DIR = "debug_family_soft"
files = sorted(f for f in os.listdir(SOFT_DIR) if f.endswith("_family.soft"))

all_results = {}
errors = []

for fname in files:
    acc = fname.replace("_family.soft", "")
    with open(os.path.join(SOFT_DIR, fname)) as fh:
        samples = parse_family_soft(fh.read())

    print(f"\n{'='*70}")
    print(f"{acc}: {len(samples)} samples → classifying with {config.llm_model}...")

    try:
        results = skill._classify_samples(acc, samples)
        type_counts = Counter(r.library_type for r in results)
        review_count = sum(1 for r in results if r.needs_review)

        print(f"  Result: {dict(type_counts)}")
        if review_count:
            print(f"  ⚠ {review_count} samples need review")

        # Show first sample per type
        seen_types = set()
        for r in results:
            if r.library_type not in seen_types:
                seen_types.add(r.library_type)
                review_flag = " ⚠" if r.needs_review else ""
                print(f"  {r.library_type}: {r.accession} conf={r.confidence:.2f}{review_flag}")
                print(f"    → {r.reasoning[:100]}")

        all_results[acc] = {
            "total_samples": len(samples),
            "classified": len(results),
            "type_counts": dict(type_counts),
            "needs_review": review_count,
            "details": [
                {
                    "accession": r.accession,
                    "library_type": r.library_type,
                    "confidence": r.confidence,
                    "needs_review": r.needs_review,
                    "reasoning": r.reasoning,
                    "supplementary_files": r.supplementary_files,
                }
                for r in results
            ],
        }
    except Exception as e:
        print(f"  ✗ ERROR: {e}")
        errors.append(f"{acc}: {e}")

# Summary
print(f"\n{'='*70}")
print(f"SUMMARY: {len(all_results)}/{len(files)} series classified successfully")
if errors:
    print(f"ERRORS ({len(errors)}):")
    for e in errors:
        print(f"  - {e}")

print(f"\n{'─'*70}")
print(f"{'Series':<12s} {'Total':>5s}  {'GEX':>4s} {'ADT':>4s} {'TCR':>4s} {'BCR':>4s} {'HTO':>4s} {'ATAC':>4s} {'OTHER':>5s}  {'Review':>6s}")
print(f"{'─'*70}")
for acc, data in sorted(all_results.items()):
    tc = data["type_counts"]
    print(
        f"{acc:<12s} {data['total_samples']:>5d}  "
        f"{tc.get('GEX',0):>4d} {tc.get('ADT',0):>4d} {tc.get('TCR',0):>4d} "
        f"{tc.get('BCR',0):>4d} {tc.get('HTO',0):>4d} {tc.get('ATAC',0):>4d} "
        f"{tc.get('OTHER',0):>5d}  {data['needs_review']:>6d}"
    )

# Save full results to JSON
with open("classification_results.json", "w") as f:
    json.dump(all_results, f, indent=2)
print(f"\nFull results saved to classification_results.json")
