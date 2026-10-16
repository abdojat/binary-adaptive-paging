#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
RUNS="${RUNS:-10}"
UPDATES="${UPDATES:-128}"
QUERIES="${QUERIES:-16}"
mkdir -p results_v83b1/repetitions
{
    echo 'BAP v8.3B-1 native dynamic update pilot, not full performance evaluation'
    date -u '+UTC %FT%TZ'
    g++ --version | head -n 1
    python3 --version
    (lscpu | grep -E 'Architecture|Model name|Hypervisor vendor' || true)
    echo "RUNS=$RUNS UPDATES=$UPDATES QUERIES=$QUERIES"
} > results_v83b1/environment.txt

g++ -O3 -std=c++20 -Wall -Wextra -pedantic dynamic_benchmark_v83b1.cpp -o dynamic_benchmark_v83b1
./dynamic_benchmark_v83b1 --validate --updates 24 --queries 8 \
    --out results_v83b1/selfcheck.csv
for i in $(seq 1 "$RUNS"); do
    echo "Native pilot process $i/$RUNS"
    ./dynamic_benchmark_v83b1 --updates "$UPDATES" --queries "$QUERIES" \
        --out "results_v83b1/repetitions/run_${i}.csv"
done
python3 analyze_v83b1.py results_v83b1/repetitions/run_*.csv \
    --out results_v83b1/paired_pilot_summary.csv
