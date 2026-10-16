#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
RUNS="${RUNS:-10}"
QUERIES="${QUERIES:-4096}"
REPEATS="${REPEATS:-5}"
mkdir -p results_v81/repetitions
{
  echo 'Experiment: BAP v8.1 metadata-lookup ablation'
  echo 'C++ compiler:'
  g++ --version | head -n 1
  echo 'Python:'
  python3 --version
  echo 'CPU:'
  (lscpu | grep -E 'Model name|Architecture|Hypervisor vendor' || true)
  echo "RUNS=$RUNS QUERIES=$QUERIES REPEATS=$REPEATS"
} > results_v81/environment.txt

g++ -O3 -std=c++20 -Wall -Wextra -pedantic lookup_ablation_v81.cpp -o lookup_ablation_v81
./lookup_ablation_v81 --validate --out results_v81/selfcheck.csv --queries 64 --repeats 3
for i in $(seq 1 "$RUNS"); do
    echo "Independent run $i / $RUNS"
    ./lookup_ablation_v81 \
      --out "results_v81/repetitions/run_${i}.csv" \
      --queries "$QUERIES" --repeats "$REPEATS"
done
python3 analyze_v81.py results_v81/repetitions/run_*.csv --out results_v81/ablation_summary_v81.csv
