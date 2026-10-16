#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p results_v83b0
python3 dynamic_incremental_v83b0.py --validate --out results_v83b0/incremental_semantics_v83b0.csv
python3 dynamic_incremental_v83b0.py --sizes 10000 --starts 1 --layouts fragmented_permissions --thresholds 0.05 --seeds 1 --updates 12 --out results_v83b0/large_region_v83b0.csv
python3 - <<'PY'
import csv
from pathlib import Path
for filename,expected in (("incremental_semantics_v83b0.csv",576),("large_region_v83b0.csv",6)):
    path=Path("results_v83b0")/filename
    with path.open(newline="",encoding="utf-8") as f:
        rows=list(csv.DictReader(f))
    assert len(rows)==expected,(filename,len(rows))
    assert all(int(x["semantic_mismatches"])==0 for x in rows)
    assert all(x["update_latency_measured"]=="NO" for x in rows)
    print("CSV CHECK PASS",path,len(rows))
PY
if [[ -f results_v83a/dynamic_correctness_v83a.csv ]]; then
  python3 verify_v83b0_against_v83a.py \
    --old results_v83a/dynamic_correctness_v83a.csv \
    --new results_v83b0/incremental_semantics_v83b0.csv
else
  echo 'Old results_v83a CSV not found: skipping cross-version equivalence check'
fi
