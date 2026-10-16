#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p results_v83a
python3 dynamic_correctness_v83a.py --validate --out results_v83a/dynamic_correctness_v83a.csv
python3 dynamic_correctness_v83a.py --sizes 10000 --starts 1 --layouts fragmented_permissions --thresholds 0.05 --seeds 1 --updates 12 --out results_v83a/large_region_spotcheck.csv
python3 - <<'PY'
import csv
from pathlib import Path
for name, count in [('dynamic_correctness_v83a.csv',576),('large_region_spotcheck.csv',6)]:
    path=Path('results_v83a')/name
    with path.open(encoding='utf-8',newline='') as f: rows=list(csv.DictReader(f))
    assert len(rows)==count, (name,len(rows))
    assert {r['semantic_mismatches'] for r in rows}=={'0'},name
    print('CSV CHECK PASS:',path,len(rows),'rows')
PY
